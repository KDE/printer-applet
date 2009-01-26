project(printer-applet)
set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH}  ${CMAKE_CURRENT_SOURCE_DIR}/cmake-modules )

macro_optional_find_package(PythonLibrary)
macro_optional_find_package(SIP)

find_package(PyQt4)
IF(NOT PYQT4_FOUND)
    macro_log_feature(PYQT4_FOUND "PyQt4" "PyQt4 was not found.  It is needed by printer-applet to run. (Use -DINSTALL_PRINTER_APPLET=TRUE to install anyway)" "http://www.riverbankcomputing.co.uk/software/pyqt/intro" FALSE)
ENDIF(NOT PYQT4_FOUND)

find_package(PyKDE4)
IF(NOT PYKDE4_FOUND)
    macro_log_feature(PYKDE_FOUND "PyKDE" "PyKDE was not found.  It is needed by printer-applet to run.  (Use -DINSTALL_PRINTER_APPLET=TRUE to install anyway)" "http://websvn.kde.org/trunk/KDE/kdebindings/python/pykde4/" FALSE)
ENDIF(NOT PYKDE4_FOUND)

find_package(PyCups)
IF(NOT PYCUPS_FOUND)
    macro_log_feature(PYCUPS_FOUND "PyCups" "PyCups was not found.  It is needed by printer-applet to run.  (Use -DINSTALL_PRINTER_APPLET=TRUE to install anyway)" "http://cyberelk.net/tim/software/pycups/" FALSE)
ENDIF(NOT PYCUPS_FOUND)

IF(PYQT4_FOUND AND PYKDE4_FOUND AND PYCUPS_FOUND)
    SET(INSTALL_PRINTER_APPLET TRUE)
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
    macro_log_feature(SYSTEMCONFIGPRINTER_FOUND "system-config-printer" "system-config-printer was not found.  Some of its modules (cupshelpers.py and ppds.py) are optionally used by printer-applet for auto configure of new printers.  You should also install hal-cups-utils <https://fedorahosted.org/hal-cups-utils/>" "http://cyberelk.net/tim/software/system-config-printer/" FALSE)
ENDIF(NOT SYSTEMCONFIGPRINTER_FOUND)
