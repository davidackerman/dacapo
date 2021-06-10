from .conversion import sanatize
from dacapo.training_stats import TrainingStats
from dacapo.validation_scores import ValidationScores
from dacapo.converter import converter

from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

import yaml
from pathlib import Path
import json
from hashlib import md5
import logging

from os.path import expanduser

logger = logging.getLogger(__name__)


class DictAsMember(dict):
    def __getattr__(self, name):
        value = self[name]
        if isinstance(value, dict):
            value = DictAsMember(value)
        return value


class MongoDbStore:
    def __init__(self):
        """Create a MongoDB sync. Used to sync runs, tasks, models,
        optimizers, trainig stats, and validation scores."""

        assert Path( expanduser("~/.config/dacapo") ).exists() or Path("./dacapo.yaml").exists()
        store_config_file = (
            Path("./dacapo.yaml")
            if Path("./dacapo.yaml").exists()
            else Path( expanduser("~/.config/dacapo") )
        )
        with store_config_file.open("r") as stream:
            options = DictAsMember(**yaml.safe_load(stream))
        self.db_host = options.mongo_db_host
        self.db_name = options.mongo_db_name

        self.client = MongoClient(self.db_host)
        self.database = self.client[self.db_name]
        self.__open_collections()
        self.__init_db()

    def sync_run(
        self, run, exclude_training_stats=False, exclude_validation_scores=False
    ):
        self.__sync_run(run)

    def store_training_stats(self, run):

        stats = run.training_stats
        existing_stats = self.__read_training_stats(run.id)

        store_from_iteration = 0

        if existing_stats.trained_until() > 0:

            if stats.trained_until() > 0:

                # both current stats and DB contain data
                if stats.trained_until() > existing_stats.trained_until():
                    # current stats go further than the one in DB
                    store_from_iteration = existing_stats.trained_until()
                    print(f"STORING FROM: {store_from_iteration}")
                else:
                    # current stats are behind DB--drop DB
                    self.__delete_training_stats(run.id)
                    print("DELETING STATS")
                    deleted_stats = self.__read_training_stats(run.id)
                    assert deleted_stats.trained_until() == 0

        # store all new stats
        self.__store_training_stats(
            stats, store_from_iteration, stats.trained_until(), run.id
        )

    def read_training_stats(self, run, iteration=-1):

        run.training_stats = self.__read_training_stats(run.id, iteration)

    def store_validation_scores(self, run):

        scores = run.validation_scores
        existing_scores = self.__read_validation_scores(run.id)

        store_from_iteration = 0

        if existing_scores.validated_until() > 0:

            if scores.validated_until() > 0:

                # both current scores and DB contain data
                if scores.validated_until() > existing_scores.validated_until():
                    # current scores go further than the one in DB
                    store_from_iteration = existing_scores.validated_until()
                else:
                    # current scores are behind DB--drop DB
                    self.__delete_validation_scores(run.id)

        self.__store_validation_scores(
            scores, store_from_iteration, scores.validated_until(), run.id
        )

    def read_validation_scores(self, run):

        run.validation_scores = self.__read_validation_scores(run.id)

    def add_run(self, run):
        return self.__save_insert(self.runs, converter.unstructure(run))

    def get_run(self, run: str):
        from dacapo.configs import Run

        run_doc = self.runs.find_one({"id": run}, projection={"_id": False})
        return converter.structure(run_doc, Run)

    def add_task(self, task):
        return self.__save_insert(self.tasks, converter.unstructure(task))

    def get_task(self, task: str):
        from dacapo.tasks import Task

        task_doc = self.tasks.find_one({"id": task}, projection={"_id": False})
        return converter.structure(task_doc, Task)

    def add_dataset(self, dataset):
        return self.__save_insert(self.datasets, converter.unstructure(dataset))

    def get_dataset(self, dataset: str):
        from dacapo.data import Dataset

        return converter.structure(
            self.datasets.find_one({"id": dataset}, projection={"_id": False}), Dataset
        )

    def add_model(self, model):
        return self.__save_insert(self.models, converter.unstructure(model))

    def get_model(self, model: str):
        from dacapo.models import Model

        return converter.structure(
            self.models.find_one({"id": model}, projection={"_id": False}), Model
        )

    def add_optimizer(self, optimizer):
        return self.__save_insert(self.optimizers, converter.unstructure(optimizer))

    def get_optimizer(self, optimizer: str):
        from dacapo.optimizers import Optimizer

        return converter.structure(
            self.optimizers.find_one({"id": optimizer}, projection={"_id": False}),
            Optimizer,
        )

    def __sync_run(self, run):
        item_id = self.__save_insert(self.runs, converter.unstructure(run))
        run.id = item_id
        # Can't we just get rid of all of this?
        """
        run_id = self.get_id(run_doc)
        existing = list(self.runs.find({"id": run_id}, {"_id": False}))

        if existing:

            stored_run = existing[0]

            if not self.__same_doc(
                run_doc, stored_run, ignore=["started", "stopped", "num_parameters"]
            ):
                raise RuntimeError(
                    f"Data for run {run.id} does not match already synced "
                    f"entry. Found\n\n{stored_run}\n\nin DB, but was "
                    f"given\n\n{run_doc}"
                )

            # stored and existing are the same, except maybe for started and
            # stopped timestamp

            update_db = False
            if stored_run["started"] is None and run.started is not None:
                update_db = True
            if stored_run["stopped"] is None and run.stopped is not None:
                update_db = True

            update_current = False
            if stored_run["started"] is not None and run.started is None:
                update_current = True
            if stored_run["stopped"] is not None and run.stopped is None:
                update_current = True

            if update_db and update_current:
                raise RuntimeError(
                    f"Start and stop time of run {run.id} do not match "
                    f"already synced entry. Found\n\n{stored_run}\n\nin "
                    f"DB, but was given\n\n{run_doc}"
                )

            if update_db:
                self.runs.update({"id": run.id}, run_doc)
            elif update_current:
                run.started = stored_run["started"]
                run.stopped = stored_run["stopped"]

        else:

            self.runs.insert(run_doc)
        """

    def __sync_prediction(self, prediction):

        prediction_doc = prediction.to_dict()
        existing = list(self.predictions.find({"id": prediction.id}, {"_id": False}))

        if existing:

            stored_prediction = existing[0]

            if not self.__same_doc(
                prediction_doc,
                stored_prediction,
                ignore=["started", "stopped", "num_parameters"],
            ):
                raise RuntimeError(
                    f"Data for prediction {prediction.id} does not match already synced "
                    f"entry. Found\n\n{stored_prediction}\n\nin DB, but was "
                    f"given\n\n{prediction_doc}"
                )

            # stored and existing are the same, except maybe for started and
            # stopped timestamp

            update_db = False
            if stored_prediction["started"] is None and prediction.started is not None:
                update_db = True
            if stored_prediction["stopped"] is None and prediction.stopped is not None:
                update_db = True

            update_current = False
            if stored_prediction["started"] is not None and prediction.started is None:
                update_current = True
            if stored_prediction["stopped"] is not None and prediction.stopped is None:
                update_current = True

            if update_db and update_current:
                raise RuntimeError(
                    f"Start and stop time of prediction {prediction.id} do not match "
                    f"already synced entry. Found\n\n{stored_prediction}\n\nin "
                    f"DB, but was given\n\n{prediction_doc}"
                )

            if update_db:
                self.predictions.update({"id": prediction.id}, prediction_doc)
            elif update_current:
                prediction.started = stored_prediction["started"]
                prediction.stopped = stored_prediction["stopped"]

        else:

            self.predictions.insert(prediction_doc)

    def check_block(self, prediction_id, step_id, block_id):
        return (
            self.predictions.count(
                {"id": prediction_id, "step": step_id, "block": block_id}
            )
            >= 1
        )

    def mark_block_done(self, prediction_id, step_id, block_id, start, duration):
        doc = {
            "id": prediction_id,
            "step": step_id,
            "block": block_id,
            "start": start,
            "duration": duration,
        }
        self.predictions.insert_one(doc)

    def __sync_task(self, task):
        item_id = self.__save_insert(self.tasks, converter.unstructure(task))
        task.id = item_id

    def __sync_dataset(self, dataset):
        item_id = self.__save_insert(self.datasets, converter.unstructure(dataset))
        dataset.id = item_id

    def __sync_model(self, model):
        item_id = self.__save_insert(self.models, converter.unstructure(model))
        model.id = item_id

    def __sync_optimizer(self, optimizer):
        item_id = self.__save_insert(self.optimizers, converter.unstructure(optimizer))
        optimizer.id = item_id

    def __store_training_stats(self, stats, begin, end, run_id):

        docs = []
        for i in range(begin, end):
            docs.append(
                {
                    "run": run_id,
                    "iteration": int(stats.iterations[i]),
                    "loss": float(stats.losses[i]),
                    "time": float(stats.times[i]),
                }
            )
        if docs:
            self.training_stats.insert_many(docs)

    def __read_training_stats(self, run_id, iteration=-1):

        stats = TrainingStats()
        docs = self.training_stats.find({"run": run_id})
        for doc in docs:
            if doc["iteration"] < iteration or iteration < 0:
                stats.add_training_iteration(doc["iteration"], doc["loss"], doc["time"])
        return stats

    def __delete_training_stats(self, run_id):
        result = self.training_stats.delete_many({"run": run_id})
        assert self.training_stats.count_documents({"run": run_id}) == 0
        assert result.deleted_count > 0

    def __store_validation_scores(self, validation_scores, begin, end, run_id):

        docs = []
        for idx, iteration in enumerate(validation_scores.iterations):
            if iteration < begin or iteration >= end:
                continue
            iteration_scores = validation_scores.scores[idx]
            docs.append(
                {
                    "run": run_id,
                    "iteration": int(iteration),
                    "parameter_scores": {
                        k: {
                            "post_processing_parameters": sanatize(
                                v["post_processing_parameters"]
                            ),
                            "scores": sanatize(v["scores"]),
                        }
                        for k, v in iteration_scores.items()
                    },
                }
            )

        if docs:
            self.validation_scores.insert_many(docs)

    def __read_validation_scores(self, run_id):

        validation_scores = ValidationScores()
        docs = self.validation_scores.find({"run": run_id})
        for doc in docs:
            validation_scores.add_validation_iteration(
                doc["iteration"], doc["parameter_scores"]
            )

        return validation_scores

    def __delete_validation_scores(self, run_id):
        self.validation_scores.delete_many({"run": run_id})

    def get_id(self, data):
        return md5(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()

    def __save_insert(self, collection, data, ignore=None):

        data = sanatize(dict(data))
        data.pop("id", None)
        item_id = self.get_id(data)

        existing = None
        for _ in range(5):

            try:

                existing = collection.find_one_and_update(
                    filter={"id": item_id},
                    update={"$set": data},
                    upsert=True,
                    projection={"_id": False},
                )

            except DuplicateKeyError:

                # race condition on upsert? try dacapo to get existing doc
                continue

        if existing:

            del existing["id"]
            if not self.__same_doc(existing, data, ignore):
                raise RuntimeError(
                    f"Data for {item_id} does not match already synced "
                    f"entry. Found\n\n{existing}\n\nin DB, but was "
                    f"given\n\n{data}"
                )
        return item_id

    def __same_doc(self, a, b, ignore=None):

        if ignore:
            a = dict(a)
            b = dict(b)
            for key in ignore:
                if key in a:
                    del a[key]
                if key in b:
                    del b[key]

        # JSONify both and compare
        a = json.loads(json.dumps(a))
        b = json.loads(json.dumps(b))

        return a == b

    def __init_db(self):

        self.users.create_index([("username", ASCENDING)], name="username", unique=True)
        self.runs.create_index(
            [("id", ASCENDING), ("repetition", ASCENDING)], name="id_rep", unique=True
        )
        self.predictions.create_index(
            [("id", ASCENDING), ("step", ASCENDING), ("block", ASCENDING)],
            name="id_step_block",
            unique=True,
        )
        self.tasks.create_index([("id", ASCENDING)], name="id", unique=True)
        self.datasets.create_index([("id", ASCENDING)], name="id", unique=True)
        self.models.create_index([("id", ASCENDING)], name="id", unique=True)
        self.optimizers.create_index([("id", ASCENDING)], name="id", unique=True)
        self.training_stats.create_index(
            [("run", ASCENDING), ("iteration", ASCENDING)], name="run_it", unique=True
        )
        self.validation_scores.create_index(
            [("run", ASCENDING), ("iteration", ASCENDING)], name="run_it", unique=True
        )

    def __open_collections(self):
        """Opens the node, edge, and meta collections"""

        self.users = self.database["users"]
        self.runs = self.database["runs"]
        self.predictions = self.database["predictions"]
        self.tasks = self.database["tasks"]
        self.datasets = self.database["datasets"]
        self.models = self.database["models"]
        self.optimizers = self.database["optimizers"]
        self.training_stats = self.database["training_stats"]
        self.validation_scores = self.database["validation_scores"]
