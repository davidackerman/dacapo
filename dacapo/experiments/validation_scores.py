from importlib.metadata import metadata
from .validation_iteration_scores import ValidationIterationScores
from .tasks.evaluators import EvaluationScores
from .tasks.post_processors import PostProcessorParameters
from .datasplits.datasets import Dataset

import attr
import numpy as np
import xarray as xr
import inspect

import itertools
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


@attr.s
class ValidationScores:

    parameters: List[PostProcessorParameters] = attr.ib(
        metadata={"help_text": "The list of parameters that are being evaluated"}
    )
    datasets: List[Dataset] = attr.ib(
        metadata={"help_text": "The datasets that will be evaluated at each iteration"}
    )
    evaluation_scores: EvaluationScores = attr.ib(
        metadata={
            "help_text": "The scores that are collected on each iteration per "
            "`PostProcessorParameters` and `Dataset`"
        }
    )
    scores: List[ValidationIterationScores] = attr.ib(
        factory=lambda: list(),
        metadata={
            "help_text": "A list of evaluation scores and their associated post-processing parameters."
        },
    )

    def subscores(self, iteration_scores: List[ValidationIterationScores]):
        return ValidationScores(
            self.parameters,
            self.datasets,
            self.evaluation_scores,
            scores=iteration_scores,
        )

    def add_iteration_scores(
        self,
        iteration_scores: ValidationIterationScores,
    ):

        self.iteration_scores.append(iteration_scores)

    def delete_after(self, iteration):

        self.iteration_scores = [
            scores for scores in self.iteration_scores if scores.iteration < iteration
        ]

    def validated_until(self):
        """The number of iterations validated for (the maximum iteration plus
        one)."""

        if not self.iteration_scores:
            return 0
        return max([score.iteration for score in self.iteration_scores]) + 1

    def compare(
        self, existing_iteration_scores: List[ValidationIterationScores]
    ) -> Tuple[bool, int]:
        """
        Compares iteration stats provided from elsewhere to scores we have saved locally.
        Local scores take priority. If local scores are at a lower iteration than the
        existing ones, delete the existing ones and replace with local.
        If local iteration > existing iteration, just update existing scores with the last
        overhanging local scores.
        """
        if not existing_iteration_scores:
            return False, 0
        existing_iteration = (
            max([score.iteration for score in existing_iteration_scores]) + 1
        )
        current_iteration = self.validated_until()
        if existing_iteration > current_iteration:
            return True, 0
        else:
            return False, existing_iteration

    @property
    def criteria(self):
        return self.evaluation_scores.criteria

    @property
    def parameter_names(self):
        return self.parameters[0].parameter_names

    def to_xarray(self):
        iteration_score_shapes = [
            np.array(iteration_scores.scores).shape
            for iteration_scores in self.iteration_scores
        ]
        iteration_scores = list(self.iteration_scores)
        if not all(
            [shape == iteration_score_shapes[-1] for shape in iteration_score_shapes]
        ):
            logger.warning(
                f"Shapes are inconsistent: {iteration_score_shapes}, filtering out some"
            )
            iteration_scores = [
                iteration_score
                for shape, iteration_score in zip(
                    iteration_score_shapes, iteration_scores
                )
                if shape == iteration_score_shapes[-1]
            ]

        return xr.DataArray(
            np.array(
                [iteration_score.scores for iteration_score in iteration_scores]
            ).reshape(
                (-1, len(self.datasets), len(self.parameters), len(self.criteria))
            ),
            dims=("iterations", "datasets", "parameters", "criteria"),
            coords={
                "iterations": [
                    iteration_score.iteration
                    for iteration_score in iteration_scores
                ],
                "datasets": self.datasets,
                "parameters": self.parameters,
                "criteria": self.criteria,
            },
        )

    def best(self, array: xr.DataArray) -> List[Optional[xr.DataArray]]:
        """
        For each criterion in the criteria dimension, return the best value. May return None if there is no best.
        """
        criterion_bests = []
        for criterion in array.coords["criteria"].values:
            sub_array = array.sel(criteria=criterion)
            result = sub_array.where(sub_array == sub_array.max(), drop=True).squeeze()
            if result.size == 0:
                criterion_bests.append(None)
            if result.size == 1:
                criterion_bests.append(result)
            else:
                for coord in itertools.product(
                    *[coords.values for coords in result.coords]
                ):
                    current = result.sel(
                        **{d: [c] for d, c in zip(result.coords.keys(), coord)}
                    )
                    if current.value != float("nan"):
                        criterion_bests.append(current)
        return criterion_bests

    def get_best(
        self, data: xr.DataArray, dim: str
    ) -> Tuple[xr.DataArray, xr.DataArray]:
        """
        Compute the Best scores along dimension "dim" per criterion.
        Returns both the index associated with the best value, and the
        best value in two seperate arrays.
        """
        if "criteria" in data.coords.keys():
            if len(data.coords["criteria"].shape) == 1:
                criteria_bests = []
                for criterion in data.coords["criteria"].values:
                    if self.evaluation_scores.higher_is_better(criterion.item()):
                        criteria_bests.append(
                            (
                                data.sel(criteria=criterion).idxmax(
                                    dim, skipna=True, fill_value=None
                                ),
                                data.sel(criteria=criterion).max(dim, skipna=True),
                            )
                        )
                    else:
                        criteria_bests.append(
                            (
                                data.sel(criteria=criterion).idxmin(
                                    dim, skipna=True, fill_value=None
                                ),
                                data.sel(criteria=criterion).min(dim, skipna=True),
                            )
                        )
                best_indexes, best_scores = zip(*criteria_bests)
                return (
                    xr.concat(best_indexes, dim=data.coords["criteria"]),
                    xr.concat(best_scores, dim=data.coords["criteria"]),
                )
            else:
                if self.evaluation_scores.higher_is_better(
                    data.coords["criteria"].item()
                ):
                    return (
                        data.idxmax(dim, skipna=True, fill_value=None),
                        data.max(dim, skipna=True),
                    )
                else:
                    return (
                        data.idxmin(dim, skipna=True, fill_value=None),
                        data.min(dim, skipna=True),
                    )

        else:
            raise ValueError("Cannot determine 'best' without knowing the criterion")

    def _get_best(self, criterion, dataset=None):
        """
        Get the best score according to this criterion.
        return iteration, parameters, score
        """
        iteration_bests = []
        for iteration_score in self.iteration_scores:
            parameters, iteration_best = iteration_score._get_best(criterion)
            iteration_bests.append(
                (iteration_score.iteration, parameters, iteration_best)
            )
