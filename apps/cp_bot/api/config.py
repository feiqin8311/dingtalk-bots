#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Config bridge for the local API compatibility layer."""

from __future__ import annotations

import os

import config as project_config

DINGTALK_APP_KEY = project_config.DINGTALK_APP_KEY
DINGTALK_APP_SECRET = project_config.DINGTALK_APP_SECRET
DINGTALK_ROBOT_CODE = project_config.DINGTALK_ROBOT_CODE
DINGTALK_API_BASE_URL = os.getenv("DINGTALK_API_BASE_URL", "https://api.dingtalk.com")
DINGTALK_GROUP_WEBHOOK = os.getenv("DINGTALK_GROUP_WEBHOOK", "")
DINGTALK_GROUP_SECRET = os.getenv("DINGTALK_GROUP_SECRET", "")
