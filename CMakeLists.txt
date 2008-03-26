set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH}  ${CMAKE_CURRENT_SOURCE_DIR}/cmake-modules )

MACRO(PYKDE4_ADD_EXECUTABLE _pyname _exename)
    INSTALL(CODE "EXECUTE_PROCESS(COMMAND ${CMAKE_COMMAND} -DTARGET=${DATA_INSTALL_DIR}/printer-applet/${_pyname} -DLINK_NAME=${BIN_INSTALL_DIR}/${_exename} -P ${CMAKE_SOURCE_DIR}/printer-applet/cmake-modules/create_exe_symlink.cmake)" )
ENDMACRO(PYKDE4_ADD_EXECUTABLE)

macro_optional_find_package(PythonLibrary)
macro_optional_find_package(SIP)

find_package(PyQt4)
IF(NOT PYQT4_FOUND)
    macro_log_feature(PYQT4_FOUND "PyQt4" "PyQt4 was not found.  It is needed by printer-applet to run." "http://www.riverbankcomputing.co.uk/pyqt/" FALSE)
ENDIF(NOT PYQT4_FOUND)

find_package(PyCups)
IF(PYCUPS_FOUND)
    install( FILES
        printer-applet-printers.ui
        printer-applet.py
        printer-applet.ui
        DESTINATION ${DATA_INSTALL_DIR}/printer-applet )
    PYKDE4_ADD_EXECUTABLE(printer-applet.py printer-applet)
else (PYCUPS_FOUND)
    macro_log_feature(PYCUPS_FOUND "PyCups" "PyCups was not found.  It is needed by printer-applet to run." "http://cyberelk.net/tim/software/pycups/" FALSE)
ENDIF(PYCUPS_FOUND)
