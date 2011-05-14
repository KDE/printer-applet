project(printer-applet)
set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH}  ${CMAKE_CURRENT_SOURCE_DIR}/cmake-modules )

find_package(KDE4)
include( KDE4Defaults )

macro_optional_find_package(PythonLibrary)
macro_optional_find_package(SIP)

find_package(PyQt4)
macro_log_feature(PYQT4_FOUND "PyQt4" "Python bindings for Qt-4.x library" "http://www.riverbankcomputing.co.uk/software/pyqt/intro" FALSE "" "Needed by printer-applet to run. (Use -DINSTALL_PRINTER_APPLET=TRUE to install anyway)")

find_package(PyKDE4)
macro_log_feature(PYKDE4_FOUND "PyKDE4" "Python bindings for KDE 4.x" "http://websvn.kde.org/trunk/KDE/kdebindings/python/pykde4/" FALSE "" "Needed by printer-applet to run. (Use -DINSTALL_PRINTER_APPLET=TRUE to install anyway)")

find_package(PyCups)
macro_log_feature(PYCUPS_FOUND "PyCups" "Python bindings for CUPS" "http://cyberelk.net/tim/software/pycups/" FALSE "" "Required by printer-applet to run.  (Use -DINSTALL_PRINTER_APPLET=TRUE to install anyway)")

IF(PYQT4_FOUND AND PYKDE4_FOUND AND PYCUPS_FOUND)
    set(INSTALL_PRINTER_APPLET TRUE)
ENDIF(PYQT4_FOUND AND PYKDE4_FOUND AND PYCUPS_FOUND)

IF(INSTALL_PRINTER_APPLET)
    install( FILES
        printer-applet-printers.ui
        printer-applet.py
        printer-applet.ui
        printer-appletui.rc
        printer-applet.notifyrc
        statereason.py
        monitor.py
        authconn.py
        debug.py
        DESTINATION ${DATA_INSTALL_DIR}/printer-applet )
    PYKDE4_ADD_EXECUTABLE(printer-applet.py printer-applet)
    install(FILES printer-applet.desktop DESTINATION ${AUTOSTART_INSTALL_DIR})
ENDIF(INSTALL_PRINTER_APPLET)

find_package(SystemConfigPrinter)
IF(NOT SYSTEMCONFIGPRINTER_FOUND)
    macro_log_feature(SYSTEMCONFIGPRINTER_FOUND "system-config-printer" "system-config-printer was not found.  Some of its modules (cupshelpers.py and ppds.py) are optionally used by printer-applet for auto configure of new printers.  You should also install the udev rules from system-config-printer." "http://cyberelk.net/tim/software/system-config-printer/" FALSE)
ENDIF(NOT SYSTEMCONFIGPRINTER_FOUND)
