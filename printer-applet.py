#!/usr/bin/env python
# -*- coding: utf-8 -*-

#############################################################################
##
## Copyright 2007-2008 Canonical Ltd
## Author: Jonathan Riddell <jriddell@ubuntu.com>
##
## Includes code from System Config Printer
## Copyright 2007 Tim Waugh <twaugh@redhat.com>
## Copyright 2007 Red Hat, Inc.
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

"""
A systray applet to show that documents are being printed, show printer warnings and errors and a GUI for hal-cups-utils automatic setup for new printers.

It is a Qt port of the applet from Red Hat's System Config Printer
http://cyberelk.net/tim/software/system-config-printer/
svn co http://svn.fedorahosted.org/svn/system-config-printer/trunk
"""

import os
import subprocess
import sys

import time

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4 import uic
from PyKDE4.kdecore import i18n, i18nc, i18np, i18ncp, ki18n, KAboutData, KCmdLineArgs, KCmdLineOptions, KStandardDirs, KLocalizedString
from PyKDE4.kdeui import KApplication, KXmlGuiWindow, KStandardAction, KIcon, KToggleAction, KNotification, KMessageBox

def translate(self, prop):
    """reimplement method from uic to change it to use gettext"""
    if prop.get("notr", None) == "true":
        return self._cstring(prop)
    else:
        if prop.text is None:
            return ""
        text = prop.text.encode("UTF-8")
        return i18n(text)

uic.properties.Properties._string = translate

import cups

import dbus
import dbus.mainloop.qt
import dbus.service

from statereason import StateReason
import monitor
import authconn
from debug import *

class PrinterURIIndex:
    def __init__ (self, names=None):
        self.printer = {}
        self.names = names

    def update_from_attrs (self, printer, attrs):
        uris = []
        if attrs.has_key ('printer-uri-supported'):
            uri_supported = attrs['printer-uri-supported']
            if type (uri_supported) != list:
                uri_supported = [uri_supported]
            uris.extend (uri_supported)
        if attrs.has_key ('notify-printer-uri'):
            uris.append (attrs['notify-printer-uri'])
        if attrs.has_key ('printer-more-info'):
            uris.append (attrs['printer-more-info'])

        for uri in uris:
            self.printer[uri] = printer

    def remove_printer (self, printer):
        # Remove references to this printer in the URI map.
        uris = self.printer.keys ()
        for uri in uris:
            if self.printer[uri] == printer:
                del self.printer[uri]

    def lookup (self, uri, connection=None):
        try:
            return self.printer[uri]
        except KeyError:
            if connection == None:
                connection = cups.Connection ()

            r = ['printer-name', 'printer-uri-supported', 'printer-more-info']
            try:
                attrs = connection.getPrinterAttributes (uri=uri,
                                                         requested_attributes=r)
            except TypeError:
                # requested_attributes argument is new in pycups 1.9.40.
                attrs = connection.getPrinterAttributes (uri=uri)
            except TypeError:
                # uri argument is new in pycups 1.9.32.  We'll have to try
                # each named printer.
                debugprint ("PrinterURIIndex: using slow method")
                if self.names == None:
                    dests = connection.getDests ()
                    names = set()
                    for (printer, instance) in dests.keys ():
                        if printer == None:
                            continue
                        if instance != None:
                            continue
                        names.add (printer)
                    self.names = names

                r = ['printer-uri-supported', 'printer-more-info']
                for name in self.names:
                    try:
                        attrs = connection.getPrinterAttributes (name,
                                                                 requested_attributes=r)
                    except TypeError:
                        # requested_attributes argument is new in pycups 1.9.40.
                        attrs = connection.getPrinterAttributes (name)

                    self.update_from_attrs (name, attrs)
                    try:
                        return self.printer[uri]
                    except KeyError:
                        pass
                raise KeyError
            except cups.IPPError:
                # URI not known.
                raise KeyError

            name = attrs['printer-name']
            self.update_from_attrs (name, attrs)
            self.printer[uri] = name
            try:
                return self.printer[uri]
            except KeyError:
                pass
        raise KeyError

class MainWindow(KXmlGuiWindow):
    """Our main GUI dialogue, overridden so that closing it doesn't quit the app"""

    def closeEvent(self, event):
        event.ignore()
        self.hide()

class PrintersWindow(QWidget):
    """The printer status dialogue, overridden so that closing it doesn't quit the app and to untick the show menu entry"""

    def __init__(self, applet):
        QWidget.__init__(self)
        self.applet = applet

    def closeEvent(self, event):
        event.ignore()
        self.applet.on_printer_status_delete_event()
        self.hide()

def collect_printer_state_reasons (connection):
    result = []
    printers = connection.getPrinters ()
    for name, printer in printers.iteritems ():
        reasons = printer["printer-state-reasons"]
        if type (reasons) == str:
            # Work around a bug that was fixed in pycups-1.9.20.
            reasons = [reasons]
        for reason in reasons:
            if reason == "none":
                break
            if (reason.startswith ("moving-to-paused") or
                reason.startswith ("paused") or
                reason.startswith ("shutdown") or
                reason.startswith ("stopping") or
                reason.startswith ("stopped-partly")):
                continue
            result.append (StateReason (name, reason))
    return result

def worst_printer_state_reason (connection, printer_reasons=None):
    """Fetches the printer list and checks printer-state-reason for
    each printer, returning a StateReason for the most severe
    printer-state-reason, or None."""
    worst_reason = None
    if printer_reasons == None:
        printer_reasons = collect_printer_state_reasons (connection)
    for reason in printer_reasons:
        if worst_reason == None:
            worst_reason = reason
            continue
        if reason > worst_reason:
            worst_reason = reason

    return worst_reason


class JobManager(QObject, monitor.Watcher):
    """our main class creates the systray icon and the dialogues and refreshes the dialogues for new information"""
    def __init__(self, parent = None):
        QObject.__init__(self)

        self.trayicon = True
        self.suppress_icon_hide = False
        self.printer_state_reasons = {}
        self.num_jobs_when_hidden = 0
        self.jobs = {}
        self.jobiters = {}
        self.will_update_job_creation_times = False # whether timeout is set FIXME now job_creation_times_timer
        self.update_job_creation_times_timer = QTimer(self)
        self.connect(self.update_job_creation_times_timer, SIGNAL("timeout()"), self.update_job_creation_times)
        self.statusbar_set = False
        self.connecting_to_device = {} # dict of printer->time first seen
        self.state_reason_notifications = {}
        self.special_status_icon = False
        self.reasoniters = {}

        #Use local files if in current directory
        if os.path.exists("printer-applet.ui"):
            APPDIR = QDir.currentPath()
        else:
            file =  KStandardDirs.locate("appdata", "printer-applet.ui")
            APPDIR = file.left(file.lastIndexOf("/"))

        self.mainWindow = MainWindow()
        uic.loadUi(APPDIR + "/" + "printer-applet.ui", self.mainWindow)

        self.printersWindow = PrintersWindow(self)
        uic.loadUi(APPDIR + "/" + "printer-applet-printers.ui", self.printersWindow)

        self.sysTray = QSystemTrayIcon(KIcon("printer"), self.mainWindow)
        #self.sysTray.show()
        self.connect(self.sysTray, SIGNAL("activated( QSystemTrayIcon::ActivationReason )"), self.toggle_window_display)

        self.menu = QMenu()
        self.menu.addAction(i18n("_Hide").replace("_", ""), self.on_icon_hide_activate)
        self.menu.addAction(KIcon("application-exit"), i18n("Quit"), self.on_icon_quit_activate)
        self.sysTray.setContextMenu(self.menu)

        self.mainWindow.treeWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.connect(self.mainWindow.treeWidget, SIGNAL("customContextMenuRequested(const QPoint&)"), self.show_treeview_popup_menu)
        #self.connect(self.mainWindow.treeWidget, SIGNAL("itemClicked(QTreeWidgetItem*, int)"), self.printItemClicked)
        self.rightClickMenu = QMenu(self.mainWindow.treeWidget)
        self.cancel = self.rightClickMenu.addAction(i18n("Cancel"), self.on_job_cancel_activate)
        self.hold = self.rightClickMenu.addAction(i18n("_Hold").replace("_",""), self.on_job_hold_activate)
        self.release = self.rightClickMenu.addAction(i18n("_Release").replace("_",""), self.on_job_release_activate)
        self.reprint = self.rightClickMenu.addAction(i18n("Re_print").replace("_",""), self.on_job_reprint_activate)

        closeAction = KStandardAction.close(self.hideMainWindow, self.mainWindow.actionCollection());

        refreshAction = self.mainWindow.actionCollection().addAction("refresh")
        refreshAction.setIcon( KIcon("view-refresh") )
        refreshAction.setText( i18n( "&Refresh" ) )
        refreshAction.setShortcut(QKeySequence(Qt.Key_F5))
        self.connect(refreshAction, SIGNAL("triggered(bool)"), self.on_refresh_activate);

        showCompletedJobsAction = KToggleAction("Show Completed Jobs", self.mainWindow)
        self.mainWindow.actionCollection().addAction("show_completed_jobs", showCompletedJobsAction)
        self.connect(showCompletedJobsAction, SIGNAL("triggered(bool)"), self.on_show_completed_jobs_activate);

        showPrinterStatusAction = KToggleAction("Show Printer Status", self.mainWindow)
        self.mainWindow.actionCollection().addAction("show_printer_status", showPrinterStatusAction)
        self.connect(showPrinterStatusAction, SIGNAL("triggered(bool)"), self.on_show_printer_status_activate);
        
        self.mainWindow.treeWidget.header().setResizeMode(QHeaderView.ResizeToContents)
        self.printersWindow.treeWidget.header().setResizeMode(QHeaderView.ResizeToContents)

        self.mainWindow.createGUI(APPDIR + "/printer-appletui.rc")

        dbus.mainloop.qt.DBusQtMainLoop(set_as_default=True)

        try:
            bus = dbus.SystemBus()
        except:
            print >> sys.stderr, "%s: printer-applet failed to connect to system D-Bus"
            sys.exit (1)

        self.monitor = monitor.Monitor (self, bus=bus, my_jobs=True,
                                        specific_dests=None)

        try:
            import cupshelpers.ppds
            notification = NewPrinterNotification(bus, self)
        except ImportError:
            pass  # cupshelpers not installed, no new printer notification will be shown

    def cleanup (self):
        self.monitor.cleanup ()
        if self.exit_handler:
            self.exit_handler (self)

    """Used in gtk frontend to set magnifing glass icon when configuring printer, I don't have a suitable icon so using notifications instead
    # Handle "special" status icon
    def set_special_statusicon (self, iconname):
        self.special_status_icon = True
        self.statusicon.set_from_icon_name (iconname)
        self.set_statusicon_visibility ()

    def unset_special_statusicon (self):
        self.special_status_icon = False
        self.statusicon.set_from_pixbuf (self.saved_statusicon_pixbuf)
    """

    def notify_new_printer (self, printer, title, text):
        self.sysTray.show()
        KNotification.event(title, text, KIcon("konqueror").pixmap(QSize(22,22)))

    """unused, see set_special_statusicon
    def set_statusicon_from_pixbuf (self, pb):
        self.saved_statusicon_pixbuf = pb
        if not self.special_status_icon:
            self.statusicon.set_from_pixbuf (pb)
    """

    """unused, see MainWindow and PrintersWindow
    def on_delete_event(self, *args):
        if self.trayicon:
            self.MainWindow.hide ()
            if self.show_printer_status.get_active ():
                self.PrintersWindow.hide ()
        else:
            self.loop.quit ()
        return True
    """

    def on_printer_status_delete_event(self):
        self.mainWindow.actionShow_Printer_Status.setChecked(False)

    def show_IPP_Error(self, exception, message):
        if exception == cups.IPP_NOT_AUTHORIZED:
            error_text = ('<span weight="bold" size="larger">' +
                          i18n('Not authorized') + '</span>\n\n' +
                          i18n('The password may be incorrect.'))
        else:
            error_text = ('<span weight="bold" size="larger">' +
                          i18n('CUPS server error') + '</span>\n\n' +
                          i18n("There was an error during the CUPS "\
                            "operation: '%1'.", message))
        #fix Gtk's non-HTML for Qt
        error_text = error_text.replace("\n", "<br />")
        error_text = error_text.replace("span", "strong")
        KMessageBox.error(self.mainWindow, error_text, i18n("Error"))

    def toggle_window_display(self, activationReason):
        if activationReason == QSystemTrayIcon.Trigger:
            if self.mainWindow.isVisible():
                self.mainWindow.hide()
            else:
                self.mainWindow.show()
                self.monitor.refresh()
    
    #FIXME, hide printer status window?
    def hideMainWindow(self):
        self.mainWindow.hide()

    def on_show_completed_jobs_activate(self, activated):
        if activated:
            self.monitor.which_jobs = "all"
        else:
            self.monitor.which_jobs = "not-completed"
        self.monitor.refresh()

    def on_show_printer_status_activate(self, activated):
        if activated:
            self.printersWindow.show()
        else:
            self.printersWindow.hide()

    """not using notifications in qt frontend
    def on_notification_closed(self, notify):
    """

    def update_job_creation_times(self):
        now = time.time ()
        need_update = False
        for job, data in self.jobs.iteritems():
            if self.jobs.has_key (job):
                iter = self.jobiters[job]

            t = "Unknown"
            if data.has_key ('time-at-creation'):
                created = data['time-at-creation']
                ago = now - created
                if ago > 86400:
                    t = time.ctime (created)
                elif ago > 3600:
                    need_update = True
                    hours = int (ago / 3600)
                    mins = int ((ago % 3600) / 60)
                    if mins > 0:
                        th = unicode(i18ncp("%1 in the '%1 and %2 ago' message below", "1 hour", "%1 hours", hours), 'utf-8')
                        tm = unicode(i18ncp("%2 in the '%1 and %2 ago' message below", "1 minute", "%1 minutes", hours), 'utf-8')
                        t = i18nc("Arguments are formatted hours and minutes from the messages above", "%1 and %2 ago", th, tm)
                    else:
                        t = i18np("1 hour ago", "%1 hours ago", hours)
                else:
                    need_update = True
                    mins = int(ago / 60)
                    t = i18np("a minute ago", "%1 minutes ago", mins)

            iter.setText(5, t)

        if need_update and not self.will_update_job_creation_times:
            self.update_job_creation_times_timer.setInterval(60 * 1000)
            self.update_job_creation_times_timer.start()
            self.will_update_job_creation_times = True

        if not need_update:
            self.update_job_creation_times_timer.stop()
            self.will_update_job_creation_times = False

        # Return code controls whether the timeout will recur.
        return self.will_update_job_creation_times

    def print_error_dialog_response(self, response, jobid):
        self.stopped_job_prompts.remove (jobid)
        if response == KMessageBox.No:
            # Diagnose
            if not self.__dict__.has_key ('troubleshooter'):
                print "FIXME implement troubleshooter"
                #import troubleshoot
                #troubleshooter = troubleshoot.run (self.on_troubleshoot_quit)
                #self.troubleshooter = troubleshooter

    def add_job (self, job, data):
        iter = QTreeWidgetItem(self.mainWindow.treeWidget)
        iter.setText(0, str(job))
        iter.setText(1, data.get('job-originating-user-name', i18nc("User who printed is not known", 'Unknown')))
        iter.setText(2, data.get('job-name', i18nc("Print job name is not known", 'Unknown')))
        self.mainWindow.treeWidget.addTopLevelItem(iter)
        self.jobiters[job] = iter
        self.update_job (job, data)
        self.update_job_creation_times ()

    def update_job (self, job, data):
        iter = self.jobiters[job]
        self.jobs[job] = data

        printer = data['job-printer-name']
        iter.setText(3, printer)

        size = i18n("Unknown")
        if data.has_key ('job-k-octets'):
            size = str (data['job-k-octets']) + 'k'
        iter.setText(4, size)

        state = None
        job_requires_auth = False
        if data.has_key ('job-state'):
            try:
                jstate = data['job-state']
                s = int (jstate)
                job_requires_auth = (jstate == cups.IPP_JOB_HELD and
                                     data.get ('job-hold-until', 'none') ==
                                     'auth-info-required')
                if job_requires_auth:
                    state = i18n("Held for authentication")
                else:
                    state = { cups.IPP_JOB_PENDING: i18nc("Job state", "Pending"),
                              cups.IPP_JOB_HELD: i18nc("Job state", "Held"),
                              cups.IPP_JOB_PROCESSING: i18nc("Job state", "Processing"),
                              cups.IPP_JOB_STOPPED: i18nc("Job state", "Stopped"),
                              cups.IPP_JOB_CANCELED: i18nc("Job state", "Canceled"),
                              cups.IPP_JOB_ABORTED: i18nc("Job state", "Aborted"),
                              cups.IPP_JOB_COMPLETED: i18nc("Job state", "Completed") }[s]
            except ValueError:
                pass
            except IndexError:
                pass

        if state == None:
            state = i18n("Unknown")
        iter.setText(6, state)

        """FIXME TODO
        # Check whether authentication is required.
        if self.trayicon:
            if (job_requires_auth and
                not self.auth_notifications.has_key (job) and
                not self.auth_info_dialogs.has_key (job)):
                try:
                    cups.require ("1.9.37")
                except:
                    debugprint ("Authentication required but "
                                "authenticateJob() not available")
                    return

                title = i18n("Authentication Required")
                text = i18n("Job requires authentication to proceed.")
                notification = pynotify.Notification (title, text, 'printer')
                notification.set_data ('job-id', job)
                notification.set_urgency (pynotify.URGENCY_NORMAL)
                notification.set_timeout (pynotify.EXPIRES_NEVER)
                notification.connect ('closed',
                                      self.on_auth_notification_closed)
                self.set_statusicon_visibility ()
                notification.attach_to_status_icon (self.statusicon)
                notification.add_action ("authenticate", i18n("Authenticate"),
                                         self.on_auth_notification_authenticate)
                notification.show ()
                self.auth_notifications[job] = notification
            elif (not job_requires_auth and
                  self.auth_notifications.has_key (job)):
                self.auth_notifications[job].close ()
        """

    def set_statusicon_visibility (self):
        if not self.trayicon:
            return

        if self.suppress_icon_hide:
            # Avoid hiding the icon if we've been woken up to notify
            # about a new printer.
            self.suppress_icon_hide = False
            return

        num_jobs = len (self.jobs.keys ())

        debugprint ("num_jobs: %d" % num_jobs)
        debugprint ("num_jobs_when_hidden: %d" % self.num_jobs_when_hidden)

        self.sysTray.setVisible(self.special_status_icon or
                                     num_jobs > self.num_jobs_when_hidden)

    def show_treeview_popup_menu(self, postition):
        # Right-clicked.
        items = self.mainWindow.treeWidget.selectedItems ()
        if len(items) != 1:
            return
        iter = items[0]
        if iter == None:
            return

        self.jobid = int(iter.text(0))
        job = self.jobs[self.jobid]
        self.cancel.setEnabled (True)
        self.hold.setEnabled (True)
        self.release.setEnabled (True)
        self.reprint.setEnabled (True)
        if job.has_key ('job-state'):
            s = job['job-state']
            if s >= cups.IPP_JOB_CANCELED:
                self.cancel.setEnabled (False)
            if s != cups.IPP_JOB_PENDING:
                self.hold.setEnabled (False)
            if s != cups.IPP_JOB_HELD:
                self.release.setEnabled (False)
            if (not job.get('job-preserved', False)):
                self.reprint.setEnabled (False)
        self.rightClickMenu.popup(QCursor.pos())

    def on_icon_popupmenu(self, icon, button, time):
        self.icon_popupmenu.popup (None, None, None, button, time)

    def on_icon_hide_activate(self):
        self.num_jobs_when_hidden = len (self.jobs.keys ())
        self.set_statusicon_visibility ()

    def on_icon_quit_activate(self):
        app.quit()

    def on_job_cancel_activate(self):
        try:
            c = authconn.Connection (self.mainWindow)
            c.cancelJob (self.jobid)
            del c
        except cups.IPPError, (e, m):
            if (e != cups.IPP_NOT_POSSIBLE and
                e != cups.IPP_NOT_FOUND):
                self.show_IPP_Error (e, m)
            self.monitor.refresh ()
            return
        except RuntimeError:
            return

        self.monitor.refresh ()

    def on_job_hold_activate(self):
        try:
            c = authconn.Connection (self.mainWindow)
            c.setJobHoldUntil (self.jobid, "indefinite")
            del c
        except cups.IPPError, (e, m):
            if (e != cups.IPP_NOT_POSSIBLE and
                e != cups.IPP_NOT_FOUND):
                self.show_IPP_Error (e, m)
            self.monitor.refresh ()
            return
        except RuntimeError:
            return

        self.monitor.refresh ()

    def on_job_release_activate(self):
        try:
            c = authconn.Connection (self.mainWindow)
            c.setJobHoldUntil (self.jobid, "no-hold")
            del c
        except cups.IPPError, (e, m):
            if (e != cups.IPP_NOT_POSSIBLE and
                e != cups.IPP_NOT_FOUND):
                self.show_IPP_Error (e, m)
            self.monitor.refresh ()
            return
        except RuntimeError:
            return

        self.monitor.refresh ()

    def on_job_reprint_activate(self):
        try:
            c = authconn.Connection (self.mainWindow)
            c.restartJob (self.jobid)
            del c
        except cups.IPPError, (e, m):
            self.show_IPP_Error (e, m)
            self.monitor.refresh ()
            return
        except RuntimeError:
            return

        self.monitor.refresh ()

    def on_refresh_activate(self, menuitem):
        self.monitor.refresh ()

    def job_is_active (self, jobdata):
        state = jobdata.get ('job-state', cups.IPP_JOB_CANCELED)
        if state >= cups.IPP_JOB_CANCELED:
            return False

        return True
 
    def set_statusicon_tooltip (self, tooltip=None):
        if not self.trayicon:
            return

        if tooltip == None:
            num_jobs = len (self.jobs)
            if num_jobs == 0:
                tooltip = i18n("No documents queued")
            else:
                tooltip = i18np("1 document queued", "%1 documents queued", num_jobs)

        self.sysTray.setToolTip(tooltip)

    def update_status (self, have_jobs=None):
        # Found out which printer state reasons apply to our active jobs.
        upset_printers = set()
        for printer, reasons in self.printer_state_reasons.iteritems ():
            if len (reasons) > 0:
                upset_printers.add (printer)
        debugprint ("Upset printers: %s" % upset_printers)

        my_upset_printers = set()
        if len (upset_printers):
            my_upset_printers = set()
            for jobid in self.active_jobs:
                # 'job-printer-name' is set by job_added/job_event
                printer = self.jobs[jobid]['job-printer-name']
                if printer in upset_printers:
                    my_upset_printers.add (printer)
            debugprint ("My upset printers: %s" % my_upset_printers)

        my_reasons = []
        for printer in my_upset_printers:
            my_reasons.extend (self.printer_state_reasons[printer])

        # Find out which is the most problematic.
        self.worst_reason = None
        if len (my_reasons) > 0:
            worst_reason = my_reasons[0]
            for reason in my_reasons:
                if reason > worst_reason:
                    worst_reason = reason
            self.worst_reason = worst_reason
            debugprint ("Worst reason: %s" % worst_reason)

        if self.worst_reason != None:
            (title, tooltip) = self.worst_reason.get_description ()
            self.mainWindow.statusBar().showMessage(tooltip)
            self.statusbar_set = True
        else:
            tooltip = None
            if self.statusbar_set:
                self.mainWindow.statusBar().clearMessage()
                self.statusbar_set = False

        if self.trayicon:
            self.set_statusicon_visibility ()
            self.set_statusicon_tooltip (tooltip=tooltip)

    ## Notifications
    def notify_printer_state_reason_if_important (self, reason):
        level = reason.get_level ()
        if level < StateReason.WARNING:
            # Not important enough to justify a notification.
            return

        self.notify_printer_state_reason (reason)

    def notify_printer_state_reason (self, reason):        
        tuple = reason.get_tuple ()
        if self.state_reason_notifications.has_key (tuple):
            debugprint ("Already sent notification for %s" % repr (reason))
            return

        """port?
        level = reason.get_level ()
        if (level == StateReason.ERROR or
            reason.get_reason () == "connecting-to-device"):
            urgency = pynotify.URGENCY_NORMAL
        else:
            urgency = pynotify.URGENCY_LOW
        """

        (title, text) = reason.get_description ()
        KNotification.event("Other", text, KIcon("konqueror").pixmap(QSize(22,22)))
        self.set_statusicon_visibility ()

    ## monitor.Watcher interface
    def current_printers_and_jobs (self, mon, printers, jobs):
        self.mainWindow.treeWidget.clear()
        self.jobs = {}
        self.jobiters = {}
        self.printer_uri_index = PrinterURIIndex (names=printers)
        connection = None
        for jobid, jobdata in jobs.iteritems ():
            uri = jobdata.get ('job-printer-uri', '')
            try:
                printer = self.printer_uri_index.lookup (uri,
                                                         connection=connection)
            except KeyError:
                printer = uri
            jobdata['job-printer-name'] = printer

            self.add_job (jobid, jobdata)

            # Fetch complete attributes for these jobs.
            attrs = None
            try:
                if connection == None:
                    connection = cups.Connection ()
                attrs = connection.getJobAttributes (jobid)
            except RuntimeError:
                pass
            except AttributeError:
                pass

            if attrs:
                jobdata.update (attrs)
                self.update_job (jobid, jobdata)

        self.jobs = jobs
        self.active_jobs = set()
        for jobid, jobdata in jobs.iteritems ():
            if self.job_is_active (jobdata):
                self.active_jobs.add (jobid)

        self.update_status ()

    def job_added (self, mon, jobid, eventname, event, jobdata):
        monitor.Watcher.job_added (self, mon, jobid, eventname, event, jobdata)

        uri = jobdata.get ('job-printer-uri', '')
        try:
            printer = self.printer_uri_index.lookup (uri)
        except KeyError:
            printer = uri
        jobdata['job-printer-name'] = printer

        # We may be showing this job already, perhaps because we are showing
        # completed jobs and one was reprinted.
        if not self.jobiters.has_key (jobid):
            self.add_job (jobid, jobdata)

        self.active_jobs.add (jobid)
        self.update_status (have_jobs=True)
        if self.trayicon:
            if not self.job_is_active (jobdata):
                return

            for reason in self.printer_state_reasons.get (printer, []):
                if not reason.user_notified:
                    self.notify_printer_state_reason_if_important (reason)


    def job_event (self, mon, jobid, eventname, event, jobdata):
        monitor.Watcher.job_event (self, mon, jobid, eventname, event, jobdata)

        uri = jobdata.get ('job-printer-uri', '')
        try:
            printer = self.printer_uri_index.lookup (uri)
        except KeyError:
            printer = uri
        jobdata['job-printer-name'] = printer

        if self.job_is_active (jobdata):
            self.active_jobs.add (jobid)
        elif jobid in self.active_jobs:
            self.active_jobs.remove (jobid)

        # Look out for stopped jobs.
        if (self.trayicon and eventname == 'job-stopped' and
            not jobid in self.stopped_job_prompts):
            # Why has the job stopped?  It might be due to a job error
            # of some sort, or it might be that the backend requires
            # authentication.  If the latter, the job will be held not
            # stopped, and the job-hold-until attribute will be
            # 'auth-info-required'.  This will be checked for in
            # update_job.
            if jobdata['job-state'] == cups.IPP_JOB_HELD:
                try:
                    # Fetch the job-hold-until attribute, as this is
                    # not provided in the notification attributes.
                    c = cups.Connection ()
                    attrs = c.getJobAttributes (jobid)
                    jobdata.update (attrs)
                except cups.IPPError:
                    pass
                except RuntimeError:
                    pass

            may_be_problem = True
            if (jobdata['job-state'] == cups.IPP_JOB_HELD and
                jobdata['job-hold-until'] == 'auth-info-required'):
                # Leave this to update_job to deal with.
                may_be_problem = False
            else:
                # Other than that, unfortunately the only
                # clue we get is the notify-text, which is not
                # translated into our native language.  We'd better
                # try parsing it.  In CUPS-1.3.6 the possible strings
                # are:
                #
                # "Job stopped due to filter errors; please consult
                # the error_log file for details."
                #
                # "Job stopped due to backend errors; please consult
                # the error_log file for details."
                #
                # "Job held due to backend errors; please consult the
                # error_log file for details."
                #
                # "Authentication is required for job %d."
                # [This case is handled in the update_job method.]
                #
                # "Job stopped due to printer being paused"
                # [This should be ignored, as the job was doing just
                # fine until the printer was stopped for other reasons.]
                notify_text = event['notify-text']
                document = jobdata['job-name']
                if notify_text.find ("backend errors") != -1:
                    message = i18n("There was a problem sending document `%1' "
                                "(job %2) to the printer.", document, jobid)
                elif notify_text.find ("filter errors") != -1:
                    message = i18n("There was a problem processing document `%1' "
                                "(job %2).", document, jobid)
                elif notify_text.find ("being paused") != -1:
                    may_be_problem = False
                else:
                    # Give up and use the provided message untranslated.
                    message = i18n("There was a problem printing document `%1' "
                                "(job %2): `%3'.", document, jobid,
                                                      notify_text)

            if may_be_problem:

                markup = ('<span weight="bold" size="larger">' +
                          i18n("Print Error") + '</span><br /><br />' +
                          message)
                try:
                    if event['printer-state'] == cups.IPP_PRINTER_STOPPED:
                        name = event['printer-name']
                        markup += ' '
                        markup += i18n("The printer called `%1' has "
                                       "been disabled.", name)
                except KeyError:
                    pass

                self.stopped_job_prompts.add (jobid)
                result = KMessageBox.warning(self.mainWindow, markup, i18n("Print Error"))
                #FIXME GTK version asks a question here but we don't have troubleshooter anyway
                #self.print_error_dialog_response(result, jobid)

        self.update_job (jobid, jobdata)

    def job_removed (self, mon, jobid, eventname, event):
        monitor.Watcher.job_removed (self, mon, jobid, eventname, event)
        if self.jobiters.has_key (jobid):

            index = self.mainWindow.treeWidget.indexOfTopLevelItem(self.jobiters[jobid])
            self.mainWindow.treeWidget.takeTopLevelItem(index)
            del self.jobiters[jobid]
            del self.jobs[jobid]

        if jobid in self.active_jobs:
            self.active_jobs.remove (jobid)

        self.update_status ()

    def state_reason_added (self, mon, reason):
        monitor.Watcher.state_reason_added (self, mon, reason)

        (title, text) = reason.get_description ()
        printer = reason.get_printer ()
        
        iter = QTreeWidgetItem(self.printersWindow.treeWidget)
        iter.setText(0, reason.get_printer ())
        iter.setText(1, printer)
        iter.setText(1, text)
        self.printersWindow.treeWidget.addTopLevelItem(iter)
        self.reasoniters[reason.get_tuple ()] = iter

        try:
            l = self.printer_state_reasons[printer]
        except KeyError:
            l = []
            self.printer_state_reasons[printer] = l

        reason.user_notified = False
        l.append (reason)
        self.update_status ()

        if not self.trayicon:
            return

        # Find out if the user has jobs queued for that printer.
        for job, data in self.jobs.iteritems ():
            if not self.job_is_active (data):
                continue
            if data['job-printer-name'] == printer:
                # Yes!  Notify them of the state reason, if necessary.
                self.notify_printer_state_reason_if_important (reason)
                break

    def state_reason_removed (self, mon, reason):
        monitor.Watcher.state_reason_removed (self, mon, reason)

        try:
            iter = self.reasoniters[reason.get_tuple ()]
            index = self.printersWindow.treeWidget.indexOfTopLevelItem(iter)
            self.printersWindow.treeWidget.takeTopLevelItem(index)
        except KeyError:
            debugprint ("Reason iter not found")

        printer = reason.get_printer ()
        try:
            reasons = self.printer_state_reasons[printer]
        except KeyError:
            debugprint ("Printer not found")
            return

        try:
            i = reasons.index (reason)
        except IndexError:
            debugprint ("Reason not found")
            return

        del reasons[i]

        self.update_status ()

        if not self.trayicon:
            return

    def still_connecting (self, mon, reason):
        monitor.Watcher.still_connecting (self, mon, reason)
        if not self.trayicon:
            return

        self.notify_printer_state_reason (reason)

    def now_connected (self, mon, printer):
        monitor.Watcher.now_connected (self, mon, printer)

        if not self.trayicon:
            return

        # Find the connecting-to-device state reason.
        try:
            reasons = self.printer_state_reasons[printer]
            reason = None
            for r in reasons:
                if r.get_reason () == "connecting-to-device":
                    reason = r
                    break
        except KeyError:
            debugprint ("Couldn't find state reason (no reasons)!")

        if reason != None:
            tuple = reason.get_tuple ()
        else:
            debugprint ("Couldn't find state reason in list!")
            for (level,
                 p,
                 r) in self.state_reason_notifications.keys ():
                if p == printer and r == "connecting-to-device":
                    debugprint ("Found from notifications list")
                    tuple = (level, p, r)
                    break

        try:
            notification = self.state_reason_notifications[tuple]
        except KeyError:
            debugprint ("Unexpected now_connected signal")
            return

        notification.close ()

    def printer_event (self, mon, printer, eventname, event):
        monitor.Watcher.printer_event (self, mon, printer, eventname, event)
        self.printer_uri_index.update_from_attrs (printer, event)

    def printer_removed (self, mon, printer):
        monitor.Watcher.printer_removed (self, mon, printer)
        self.printer_uri_index.remove_printer (printer)

####
#### NewPrinterNotification DBus server (the 'new' way).
####
PDS_PATH="/com/redhat/NewPrinterNotification"
PDS_IFACE="com.redhat.NewPrinterNotification"
PDS_OBJ="com.redhat.NewPrinterNotification"
class NewPrinterNotification(dbus.service.Object):
    """listen for dbus signals"""
    STATUS_SUCCESS = 0
    STATUS_MODEL_MISMATCH = 1
    STATUS_GENERIC_DRIVER = 2
    STATUS_NO_DRIVER = 3

    def __init__ (self, bus, jobmanager):
        self.bus = bus
        self.getting_ready = 0
        self.jobmanager = jobmanager
        bus_name = dbus.service.BusName (PDS_OBJ, bus=bus)
        dbus.service.Object.__init__ (self, bus_name, PDS_PATH)
        #self.jobmanager.notify_new_printer ("", i18n("New Printer"), i18n("Configuring New Printer"))

    """
    def wake_up (self):
        global waitloop, runloop, jobmanager
        do_imports ()
        if jobmanager == None:
            waitloop.quit ()
            runloop = gobject.MainLoop ()
            jobmanager = JobManager(bus, runloop,
                                    service_running=service_running,
                                    trayicon=trayicon, suppress_icon_hide=True)
    """
    
    @dbus.service.method(PDS_IFACE, in_signature='', out_signature='')
    def GetReady (self):
        """hal-cups-utils is settings up a new printer"""
        self.jobmanager.notify_new_printer ("", "New Printer", i18n("Configuring New Printer"))
    """
        self.wake_up ()
        if self.getting_ready == 0:
            jobmanager.set_special_statusicon (SEARCHING_ICON)

        self.getting_ready += 1
        gobject.timeout_add (60 * 1000, self.timeout_ready)

    def timeout_ready (self):
        global jobmanager
        if self.getting_ready > 0:
            self.getting_ready -= 1
        if self.getting_ready == 0:
            jobmanager.unset_special_statusicon ()

        return False
    """

    # When I plug in my printer HAL calls this with these args:
    #status: 0
    #name: PSC_1400_series
    #mfg: HP
    #mdl: PSC 1400 series
    #des:
    #cmd: LDL,MLC,PML,DYN
    @dbus.service.method(PDS_IFACE, in_signature='isssss', out_signature='')
    def NewPrinter (self, status, name, mfg, mdl, des, cmd):
        """hal-cups-utils has set up a new printer"""
        """
        print "status: " + str(status)
        print "name: " + name
        print "mfg: " + mfg
        print "mdl: " + mdl
        print "des: " + des
        print "cmd: " + cmd
        """

        c = cups.Connection ()
        try:
            printer = c.getPrinters ()[name]
        except KeyError:
            return
        del c

        from cupshelpers.ppds import ppdMakeModelSplit
        (make, model) = ppdMakeModelSplit (printer['printer-make-and-model'])
        driver = make + " " + model
        if status < self.STATUS_GENERIC_DRIVER:
            title = "Printer Added"
        else:
            title = "Missing Printer Driver"

        if status == self.STATUS_SUCCESS:
            text = i18n("'%1' is ready for printing.", name)
        else: # Model mismatch
            text = i18n("'%1' has been added, using the '%2' driver.", name, driver)

        self.jobmanager.notify_new_printer (name, title, text)


if __name__ == "__main__":
    """start the application.  TODO, gtk frontend does clever things here to not start the GUI until it has to"""
    appName     = "printer-applet"
    catalogue   = "printer-applet"
    programName = ki18n("Printer Applet")
    version     = "1.3"
    description = ki18n("Applet to view current print jobs and configure new printers")
    license     = KAboutData.License_GPL
    copyright   = ki18n("2007-2008 Canonical Ltd")
    text        = KLocalizedString()
    homePage    = "http://utils.kde.org/projects/printer-applet"
    bugEmail    = ""

    aboutData   = KAboutData (appName, catalogue, programName, version, description,
                                license, copyright, text, homePage, bugEmail)

    aboutData.addAuthor(ki18n("Jonathan Riddell"), ki18n("Author"))
    aboutData.addAuthor(ki18n("Tim Waugh/Red Hat"), ki18n("System Config Printer Author"))

    options = KCmdLineOptions()
    options.add("show", ki18n("Show even when nothing printing"))

    KCmdLineArgs.init(sys.argv, aboutData)
    KCmdLineArgs.addCmdLineOptions(options)

    app = KApplication()

    args = KCmdLineArgs.parsedArgs()

    app.setWindowIcon(KIcon("printer"))
    if app.isSessionRestored():
         sys.exit(1)
    applet = JobManager()
    if args.isSet("show"):
        applet.mainWindow.show()
        applet.sysTray.show()
    sys.exit(app.exec_())
