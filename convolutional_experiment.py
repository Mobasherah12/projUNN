"""
File: mnist_experiments.py
Project: torchstrap
-----
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
"""

"""
File: mnist_experiments.py
Created Date: Wed Mar 09 2022
Author: Randall Balestriero
-----
Last Modified: Wed Mar 09 2022 10:07:14 PM
Modified By: Randall Balestriero
-----
Copyright (c) Meta Platforms, Inc. and affiliates.
"""
import torch
import torchvision
from torchvision import transforms
import torchmetrics
import argparse
import projunn
import numpy as np
import os


def load_data(name):

    if "CIFAR" in name:
        stats = ((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010))
        train_tfms = transforms.Compose(
            [
                transforms.RandomCrop(32, padding=4, padding_mode="reflect"),
                transforms.RandomHorizontalFlip(),
                transforms.ToTensor(),
                transforms.Normalize(*stats, inplace=True),
            ]
        )
        valid_tfms = transforms.Compose(
            [transforms.ToTensor(), transforms.Normalize(*stats)]
        )
    else:
        train_tfms = transforms.ToTensor()
        valid_tfms = transforms.ToTensor()
    train = torchvision.datasets.__dict__[name](
        "./", download=True, train=True, transform=train_tfms
    )
    test = torchvision.datasets.__dict__[name](
        "./", download=True, train=False, transform=valid_tfms
    )
    train_loader = torch.utils.data.DataLoader(
        train, batch_size=args.bs, shuffle=True, drop_last=True
    )
    test_loader = torch.utils.data.DataLoader(
        test, batch_size=args.bs, shuffle=False, drop_last=True
    )

    if name == "MNIST":
        epochs = 50
        channels = 1
        length = 28
    else:
        epochs = 90
        channels = 3
        length = 32

    return train_loader, test_loader, epochs, channels, length


parser = argparse.ArgumentParser()
parser.add_argument("-lr", type=float, default=1.0)
parser.add_argument("-lr_divider", type=float, default=10.0)
parser.add_argument("-bs", type=int, default=256)
parser.add_argument(
    "--optimizer", type=str, default="RMSProp", choices=["RMSProp", "SGD"]
)
parser.add_argument(
    "--dataset", type=str, default="CIFAR10", choices=["MNIST", "CIFAR10", "CIFAR100"]
)
parser.add_argument("-gamma", type=float, default=0.0)
parser.add_argument(
    "--projector", type=str, default="projUNND", choices=["projUNND", "projUNNT"]
)
parser.add_argument("--unitary", action="store_true")
args = parser.parse_args()


train_loader, test_loader, epochs, channels, length = load_data(args.dataset)
model = projunn.models.ResNet9(
    channels, num_classes=10, image_length=length, unitary=args.unitary
).cuda()
model.train()


# create projector and optionally the optimizer
def projector(param, update):
    a, b = projunn.utils.LSI_approximation(update, k=1)
    if args.projector == "projUNND":
        update = projunn.utils.projUNN_D(param.data, a, b, project_on=False)
    else:
        update = projunn.utils.projUNN_T(param.data, a, b, project_on=False)
    return update


if args.optimizer == "RMSProp":
    optimizer = projunn.optimizers.RMSprop(
        model.parameters(), projector=projector, lr=args.lr
    )

accuracy = torchmetrics.Accuracy(compute_on_step=False).cuda()

if args.gamma:
    regularizer = projunn.utils.OrthoRegularizer(model, [3, 3])

for epoch in range(epochs):
    accuracy.reset()
    for iter, (images, labels) in enumerate(train_loader):
        prediction = model(images.cuda())
        if args.gamma:
            loss = (
                torch.nn.functional.cross_entropy(prediction, labels.cuda())
                + regularizer.regularize() * args.gamma
            )
        else:
            loss = torch.nn.functional.cross_entropy(prediction, labels.cuda())

        model.zero_grad()
        loss.backward()
        if args.optimizer == "RMSProp":
            optimizer.step()
        else:
            for param in model.parameters():
                update = -args.lr * param.grad
                if hasattr(param, "needs_projection"):
                    update = projector(update)
                param.data.add_(update)
        with torch.no_grad():
            accuracy(prediction, labels.cuda())
            if iter % 10 == 0:
                l1_weight = model.conv1[0].weight
                diff = l1_weight @ torch.conj(l1_weight.permute(0, 2, 1)) - torch.eye(
                    l1_weight.shape[1], device="cuda"
                )
                print(
                    f"Current loss is: {loss.item()}, and how far from orthogonal? {torch.sum(diff*diff.conj())}"
                )

    print("epoch train accuracy", accuracy.compute().item())
    accuracy.reset()
    model.eval()
    with torch.no_grad():
        for iter, (images, labels) in enumerate(test_loader):
            prediction = model(images.cuda())
            accuracy(prediction, labels.cuda())
    print("epoch test accuracy", accuracy.compute().item())
    model.train()