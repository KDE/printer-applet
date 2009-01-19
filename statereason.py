#!/usr/bin/env python
# -*- coding: utf-8 -*-

#############################################################################
##
## Copyright 2007-2009 Canonical Ltd
## Author: Jonathan Riddell <jriddell@ubuntu.com>
##
## Includes code from System Config Printer
## Copyright 2007, 2008 Tim Waugh <twaugh@redhat.com>
## Copyright 2007, 2008 Red Hat, Inc.
##
## This program is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 2 of 
## the License, or (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program.  If not, see <http://www.gnu.org/licenses/>.
##
#############################################################################

class StateReason:
    """Holds problem information for a printer and can be ordered for priority 
    by comparing with another instance"""
    REPORT=1
    WARNING=2
    ERROR=3

    LEVEL_ICON={
        REPORT: "dialog-info",
        WARNING: "dialog-warning",
        ERROR: "dialog-error"
        }

    def __init__(self, printer, reason):
        self.printer = printer
        self.reason = reason
        self.level = None
        self.canonical_reason = None

    def get_printer (self):
        return self.printer

    def get_level (self):
        if self.level != None:
            return self.level

        if (self.reason.endswith ("-report") or
            self.reason == "connecting-to-device"):
            self.level = self.REPORT
        elif self.reason.endswith ("-warning"):
            self.level = self.WARNING
        else:
            self.level = self.ERROR
        return self.level

    def get_reason (self):
        if self.canonical_reason:
            return self.canonical_reason

        level = self.get_level ()
        reason = self.reason
        if level == self.WARNING and reason.endswith ("-warning"):
            reason = reason[:-8]
        elif level == self.ERROR and reason.endswith ("-error"):
            reason = reason[:-6]
        self.canonical_reason = reason
        return self.canonical_reason

    def get_description (self):
        messages = {
            'toner-low': (i18n("Toner low"),
                          ki18n("Printer '%1' is low on toner.")),
            'toner-empty': (i18n("Toner empty"),
                            ki18n("Printer '%1' has no toner left.")),
            'cover-open': (i18n("Cover open"),
                           ki18n("The cover is open on printer '%1'.")),
            'door-open': (i18n("Door open"),
                          ki18n("The door is open on printer '%1'.")),
            'media-low': (i18n("Paper low"),
                          ki18n("Printer '%1' is low on paper.")),
            'media-empty': (i18n("Out of paper"),
                            ki18n("Printer '%1' is out of paper.")),
            'marker-supply-low': (i18n("Ink low"),
                                  ki18n("Printer '%1' is low on ink.")),
            'marker-supply-empty': (i18n("Ink empty"),
                                    ki18n("Printer '%1' has no ink left.")),
            'offline': (i18n("Printer off-line"),
                        ki18n("Printer `%1' is currently offline.")),
            'connecting-to-device': (i18n("Not connected?"),
                                     ki18n("Printer '%1' may not be connected.")),
            'other': (i18n("Printer error"),
                      ki18n("There is a problem on printer `%1'.")),
            }
        try:
            (title, text) = messages[self.get_reason ()]
            text = text.subs (self.get_printer ()).toString ()
        except KeyError:
            if self.get_level () == self.REPORT:
                title = i18n("Printer report")
            elif self.get_level () == self.WARNING:
                title = i18n("Printer warning")
            elif self.get_level () == self.ERROR:
                title = i18n("Printer error")
            text = i18n("Printer '%1': '%2'.", self.get_printer (), self.get_reason ())
        return (title, text)

    def get_tuple (self):
        return (self.get_level (), self.get_printer (), self.get_reason ())

    def __cmp__(self, other):
        if other == None:
            return 1
        if other.get_level () != self.get_level ():
            return cmp (self.get_level (), other.get_level ())
        if other.get_printer () != self.get_printer ():
            return cmp (other.get_printer (), self.get_printer ())
        return cmp (other.get_reason (), self.get_reason ())
