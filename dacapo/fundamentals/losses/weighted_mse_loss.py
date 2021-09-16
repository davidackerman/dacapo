from .helpers import Loss

import torch
import attr

from typing import Optional


@attr.s
class WeightedMSELoss(Loss):

    def module(self):
        return WeightedMSELossOp()


class WeightedMSELossOp(torch.nn.MSELoss):
    def __init__(self):
        super(WeightedMSELossOp, self).__init__()

    def forward(self, prediction, target, weights):

        return super(WeightedMSELossOp, self).forward(
            prediction * weights, target * weights
        )
