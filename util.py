#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from gi.repository import GObject


def mkenumvalue(value, value_name, value_nick):
    v = GObject.EnumValue()
    v.value = value
    v.value_name = value_name
    v.value_nick = value_nick
    return v