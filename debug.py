#!/usr/bin/env python

## Copyright (C) 2008 Red Hat, Inc.
## Copyright (C) 2008 Tim Waugh <twaugh@redhat.com>

## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.

## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.

## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import sys
import traceback

_debug=True
def debugprint (x):
    if _debug:
        try:
            print x
        except:
            pass

def get_debugging ():
    return _debug

def set_debugging (d):
    global _debug
    _debug = d

def fatalException (exitcode=1):
    nonfatalException (type="fatal", end="Exiting")
    sys.exit (exitcode)

def nonfatalException (type="non-fatal", end="Continuing anyway.."):
    d = get_debugging ()
    set_debugging (True)
    debugprint ("Caught %s exception.  Traceback:" % type)
    (type, value, tb) = sys.exc_info ()
    tblast = traceback.extract_tb (tb, limit=None)
    if len (tblast):
        tblast = tblast[:len (tblast) - 1]
    extxt = traceback.format_exception_only (type, value)
    for line in traceback.format_tb(tb):
        debugprint (line.strip ())
    debugprint (extxt[0].strip ())
    debugprint (end)
    set_debugging (d)
