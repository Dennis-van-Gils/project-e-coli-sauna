#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Temperature control box Alvaro
"""
__author__ = "Dennis van Gils"
__authoremail__ = "vangils.dennis@gmail.com"
__url__ = "https://github.com/Dennis-van-Gils/project-e-coli-sauna"
__date__ = "31-08-2020"
__version__ = "1.0"
# pylint: disable=bare-except, broad-except, try-except-raise, unnecessary-lambda

import os
import sys
import time

import numpy as np
import psutil

from PyQt5 import QtCore, QtGui
from PyQt5 import QtWidgets as QtWid
from PyQt5.QtCore import QDateTime
import pyqtgraph as pg

from dvg_debug_functions import tprint, dprint, print_fancy_traceback as pft
from dvg_pyqt_controls import (
    create_Toggle_button,
    SS_TEXTBOX_READ_ONLY,
    SS_GROUP,
)
from dvg_pyqt_filelogger import FileLogger
from dvg_pyqtgraph_threadsafe import (
    HistoryChartCurve,
    LegendSelect,
    PlotManager,
)

from dvg_devices.Aim_TTi_PSU_protocol_RS232 import Aim_TTi_PSU
from dvg_devices.Aim_TTi_PSU_qdev import Aim_TTi_PSU_qdev
from dvg_devices.Arduino_protocol_serial import Arduino
from dvg_qdeviceio import QDeviceIO
from dvg_pid_controller import PID_Controller


TRY_USING_OPENGL = False
if TRY_USING_OPENGL:
    try:
        import OpenGL.GL as gl  # pylint: disable=unused-import
    except:
        print("OpenGL acceleration: Disabled")
        print("To install: `conda install pyopengl` or `pip install pyopengl`")
    else:
        print("OpenGL acceleration: Enabled")
        pg.setConfigOptions(useOpenGL=True)
        pg.setConfigOptions(antialias=True)
        pg.setConfigOptions(enableExperimental=True)

# Global pyqtgraph configuration
# pg.setConfigOptions(leftButtonPan=False)
pg.setConfigOption("foreground", "#EEE")

# Constants
DAQ_INTERVAL_MS = 1000  # [ms]
CHART_INTERVAL_MS = 500  # [ms]
CHART_HISTORY_TIME = 7200  # [s]

# Constants PID
# Tuned for parallel connected heaters, 1x 5W, 1x 10W
PID_TEMP_SETPOINT = 37.0  # ['C]
PID_Kp = 4.0
PID_Ki = 0.003
PID_V_clamp = 12  # [V], limit output voltage driven by the PID

# Show debug info in terminal? Warning: Slow! Do not leave on unintentionally.
DEBUG = False


def get_current_date_time():
    cur_date_time = QDateTime.currentDateTime()
    return (
        cur_date_time.toString("dd-MM-yyyy"),  # Date
        cur_date_time.toString("HH:mm:ss"),  # Time
        cur_date_time.toString("yyMMdd_HHmmss"),  # Reverse notation date-time
    )


# ------------------------------------------------------------------------------
#   States
# ------------------------------------------------------------------------------


class State(object):
    """Reflects the actual readings, parsed into separate variables, of the
    Arduino. There should only be one instance of the State class.
    """

    def __init__(self):
        self.time = np.nan  # [s]
        self.dht22_temp = np.nan  # ['C]
        self.dht22_humi = np.nan  # [%]
        self.pid_enabled = False  # PID controller


state = State()

# ------------------------------------------------------------------------------
#   MainWindow
# ------------------------------------------------------------------------------


class MainWindow(QtWid.QWidget):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)

        self.setWindowTitle("E. coli sauna")
        self.setGeometry(350, 50, 960, 800)
        self.setStyleSheet(SS_TEXTBOX_READ_ONLY + SS_GROUP)

        # -------------------------
        #   Top frame
        # -------------------------

        # Left box
        self.qlbl_update_counter = QtWid.QLabel("0")
        self.qlbl_DAQ_rate = QtWid.QLabel("DAQ: nan Hz")
        self.qlbl_DAQ_rate.setStyleSheet("QLabel {min-width: 7em}")

        vbox_left = QtWid.QVBoxLayout()
        vbox_left.addWidget(self.qlbl_update_counter, stretch=0)
        vbox_left.addStretch(1)
        vbox_left.addWidget(self.qlbl_DAQ_rate, stretch=0)

        # Middle box
        self.qlbl_title = QtWid.QLabel(
            "", font=QtGui.QFont("Palatino", 14, weight=QtGui.QFont.Bold),
        )
        self.qlbl_title.setAlignment(QtCore.Qt.AlignCenter)
        self.qlbl_cur_date_time = QtWid.QLabel("00-00-0000    00:00:00")
        self.qlbl_cur_date_time.setAlignment(QtCore.Qt.AlignCenter)
        self.qpbt_record = create_Toggle_button(
            "Click to start recording to file"
        )
        self.qlbl_warning = QtWid.QLabel(
            "Do not exceed 5.5 W as the heaters will reach >90 °C.",
            font=QtGui.QFont("Palatino", 8, weight=QtGui.QFont.Bold),
        )
        self.qlbl_warning.setStyleSheet(
            "QLabel {color: darkred; alignment: AlignCenter}"
        )
        self.qlbl_warning.setAlignment(QtCore.Qt.AlignCenter)
        self.qpbt_record.clicked.connect(lambda state: log.record(state))

        vbox_middle = QtWid.QVBoxLayout()
        vbox_middle.addWidget(self.qlbl_title)
        vbox_middle.addWidget(self.qlbl_cur_date_time)
        vbox_middle.addWidget(self.qpbt_record)
        vbox_middle.addWidget(self.qlbl_warning)

        # Right box
        self.qpbt_exit = QtWid.QPushButton("Exit")
        self.qpbt_exit.clicked.connect(self.close)
        self.qpbt_exit.setMinimumHeight(30)
        self.qlbl_recording_time = QtWid.QLabel(alignment=QtCore.Qt.AlignRight)

        vbox_right = QtWid.QVBoxLayout()
        vbox_right.addWidget(self.qpbt_exit, stretch=0)
        vbox_right.addStretch(1)
        vbox_right.addWidget(self.qlbl_recording_time, stretch=0)

        # Round up top frame
        hbox_top = QtWid.QHBoxLayout()
        hbox_top.addLayout(vbox_left, stretch=0)
        hbox_top.addStretch(1)
        hbox_top.addLayout(vbox_middle, stretch=0)
        hbox_top.addStretch(1)
        hbox_top.addLayout(vbox_right, stretch=0)

        # -------------------------
        #   Bottom frame
        # -------------------------

        #  Group 'PID control'
        # -------------------------

        p = {
            "alignment": QtCore.Qt.AlignRight,
            "maximumWidth": 48,
        }
        self.qpbt_pid_enabled = create_Toggle_button("PID OFF")
        self.qpbt_pid_enabled.clicked.connect(
            lambda state: self.process_qpbt_pid_enabled(state)
        )

        self.qlin_pid_temp_setp = QtWid.QLineEdit(
            "%.1f" % PID_TEMP_SETPOINT, **p
        )
        self.qlin_pid_temp_setp.editingFinished.connect(
            self.process_qlin_pid_temp_setp
        )

        self.qlin_pid_Kp = QtWid.QLineEdit("%.1f" % PID_Kp, **p)
        self.qlin_pid_Kp.editingFinished.connect(self.process_qlin_pid_Kp)

        self.qlin_pid_Ki = QtWid.QLineEdit("%.0e" % PID_Ki, **p)
        self.qlin_pid_Ki.editingFinished.connect(self.process_qlin_pid_Ki)

        self.qlin_pid_V_clamp = QtWid.QLineEdit("%.1f" % PID_V_clamp, **p)
        self.qlin_pid_V_clamp.editingFinished.connect(
            self.process_qlin_pid_V_clamp
        )

        # fmt: off
        grid = QtWid.QGridLayout()
        grid.setVerticalSpacing(2)
        grid.addWidget(self.qpbt_pid_enabled       , 0, 0, 1, 3)
        grid.addItem(QtWid.QSpacerItem(1, 2)       , 1, 0)
        grid.addWidget(QtWid.QLabel("Setpoint")    , 2, 0)
        grid.addWidget(self.qlin_pid_temp_setp     , 2, 1)
        grid.addWidget(QtWid.QLabel("°C")          , 2, 2)
        grid.addItem(QtWid.QSpacerItem(1, 10)      , 3, 0)
        grid.addWidget(QtWid.QLabel("Parameters:") , 4, 0, 1, 3)
        grid.addItem(QtWid.QSpacerItem(1, 4)       , 5, 0)
        grid.addWidget(QtWid.QLabel("K_p")         , 6, 0)
        grid.addWidget(self.qlin_pid_Kp            , 6, 1)
        grid.addWidget(QtWid.QLabel("K_i")         , 7, 0)
        grid.addWidget(self.qlin_pid_Ki            , 7, 1)
        grid.addWidget(QtWid.QLabel("1/s")         , 7, 2)
        grid.addWidget(QtWid.QLabel("Output clamp"), 8, 0)
        grid.addWidget(self.qlin_pid_V_clamp       , 8, 1)
        grid.addWidget(QtWid.QLabel("V")           , 8, 2)
        # fmt: on

        qgrp_PID = QtWid.QGroupBox("PID feedback")
        qgrp_PID.setLayout(grid)

        self.vbox_control = QtWid.QVBoxLayout()
        self.vbox_control.addWidget(qdev_psu.grpb, stretch=0)
        self.vbox_control.addWidget(qgrp_PID, stretch=0)
        self.vbox_control.addStretch()

        #  Charts
        # -------------------------

        self.gw = pg.GraphicsLayoutWidget()

        # Plot: Temperatures
        p = {"color": "#EEE", "font-size": "10pt"}
        self.pi_temp = self.gw.addPlot(row=0, col=0)
        self.pi_temp.setLabel("left", text="temperature (°C)", **p)

        # Plot: Humidity
        self.pi_humi = self.gw.addPlot(row=1, col=0)
        self.pi_humi.setLabel("left", text="humidity (%)", **p)

        # Plot: heater power
        self.pi_power = self.gw.addPlot(row=2, col=0)
        self.pi_power.setLabel("left", text="power (W)", **p)

        self.plots = [self.pi_temp, self.pi_humi, self.pi_power]
        for plot in self.plots:
            plot.setClipToView(True)
            plot.showGrid(x=1, y=1)
            plot.setLabel("bottom", text="history (s)", **p)
            plot.setMenuEnabled(True)
            plot.enableAutoRange(axis=pg.ViewBox.XAxis, enable=False)
            plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
            plot.setAutoVisible(y=True)
            plot.setRange(xRange=[-CHART_HISTORY_TIME, 0])

        # Curves
        capacity = round(CHART_HISTORY_TIME * 1e3 / DAQ_INTERVAL_MS)
        PEN_01 = pg.mkPen(color=[255, 255, 0], width=3)
        PEN_02 = pg.mkPen(color=[0, 255, 255], width=3)
        PEN_03 = pg.mkPen(color=[255, 0, 0], width=3)

        self.tscurve_dht22_temp = HistoryChartCurve(
            capacity=capacity,
            linked_curve=self.pi_temp.plot(pen=PEN_01, name="temperature"),
        )
        self.tscurve_dht22_humi = HistoryChartCurve(
            capacity=capacity,
            linked_curve=self.pi_humi.plot(pen=PEN_02, name="humidity"),
        )
        self.tscurve_power = HistoryChartCurve(
            capacity=capacity,
            linked_curve=self.pi_power.plot(pen=PEN_03, name="heater power"),
        )

        self.tscurves = [
            self.tscurve_dht22_temp,
            self.tscurve_dht22_humi,
            self.tscurve_power,
        ]

        #  Group `Readings`
        # -------------------------

        legend = LegendSelect(
            linked_curves=self.tscurves, hide_toggle_button=True
        )

        p = {
            "readOnly": True,
            "alignment": QtCore.Qt.AlignRight,
            "maximumWidth": 54,
        }
        self.qlin_ds_temp = QtWid.QLineEdit(**p)
        self.qlin_dht22_temp = QtWid.QLineEdit(**p)
        self.qlin_dht22_humi = QtWid.QLineEdit(**p)
        self.qlin_power = QtWid.QLineEdit(**p)

        # fmt: off
        legend.grid.setHorizontalSpacing(6)
        legend.grid.addWidget(self.qlin_dht22_temp    , 0, 2)
        legend.grid.addWidget(QtWid.QLabel("± 0.5 °C"), 0, 3)
        legend.grid.addWidget(self.qlin_dht22_humi    , 1, 2)
        legend.grid.addWidget(QtWid.QLabel("± 3 %")   , 1, 3)
        legend.grid.addWidget(self.qlin_power         , 2, 2)
        legend.grid.addWidget(QtWid.QLabel("± 0.05 W"), 2, 3)
        # fmt: on

        qgrp_readings = QtWid.QGroupBox("Readings")
        qgrp_readings.setLayout(legend.grid)

        #  Group 'Log comments'
        # -------------------------

        self.qtxt_comments = QtWid.QTextEdit()
        grid = QtWid.QGridLayout()
        grid.addWidget(self.qtxt_comments, 0, 0)

        qgrp_comments = QtWid.QGroupBox("Log comments")
        qgrp_comments.setLayout(grid)

        #  Group 'Charts'
        # -------------------------

        self.plot_manager = PlotManager(parent=self)
        self.plot_manager.add_autorange_buttons(linked_plots=self.plots)
        self.plot_manager.add_preset_buttons(
            linked_plots=self.plots,
            linked_curves=self.tscurves,
            presets=[
                {
                    "button_label": "03:00",
                    "x_axis_label": "history (sec)",
                    "x_axis_divisor": 60,
                    "x_axis_range": (-3, 0),
                },
                {
                    "button_label": "10:00",
                    "x_axis_label": "history (min)",
                    "x_axis_divisor": 60,
                    "x_axis_range": (-10, 0),
                },
                {
                    "button_label": "30:00",
                    "x_axis_label": "history (min)",
                    "x_axis_divisor": 60,
                    "x_axis_range": (-30, 0),
                },
                {
                    "button_label": "60:00",
                    "x_axis_label": "history (min)",
                    "x_axis_divisor": 60,
                    "x_axis_range": (-60, 0),
                },
                {
                    "button_label": "120:00",
                    "x_axis_label": "history (min)",
                    "x_axis_divisor": 60,
                    "x_axis_range": (-120, 0),
                },
            ],
        )
        self.plot_manager.add_clear_button(linked_curves=self.tscurves)
        self.plot_manager.perform_preset(1)

        qgrp_chart = QtWid.QGroupBox("Charts")
        qgrp_chart.setLayout(self.plot_manager.grid)

        vbox = QtWid.QVBoxLayout()
        vbox.addWidget(qgrp_readings)
        vbox.addWidget(qgrp_comments)
        vbox.addWidget(qgrp_chart, alignment=QtCore.Qt.AlignLeft)
        vbox.addStretch()

        # -------------------------
        #   Round up full window
        # -------------------------

        self.hbox_bot = QtWid.QHBoxLayout()
        self.hbox_bot.addLayout(self.vbox_control, 0)
        self.hbox_bot.addWidget(self.gw, 1)
        self.hbox_bot.addLayout(vbox, 0)

        vbox = QtWid.QVBoxLayout(self)
        vbox.addLayout(hbox_top, stretch=0)
        vbox.addSpacerItem(QtWid.QSpacerItem(0, 10))
        vbox.addLayout(self.hbox_bot, stretch=1)

    # --------------------------------------------------------------------------
    #   Handle controls
    # --------------------------------------------------------------------------

    @QtCore.pyqtSlot(bool)
    def process_qpbt_pid_enabled(self, state_):
        state.pid_enabled = state_
        qdev_psu.V_source.setReadOnly(state_)
        qdev_psu.I_source.setReadOnly(state_)

    @QtCore.pyqtSlot()
    def process_qlin_pid_temp_setp(self):
        try:
            temp_setp = float(self.qlin_pid_temp_setp.text())
        except (TypeError, ValueError):
            temp_setp = 25.0
        except:
            raise

        MIN_SETP = 25  # ['C]
        MAX_SETP = 40  # ['C]
        temp_setp = np.clip(temp_setp, MIN_SETP, MAX_SETP)
        self.qlin_pid_temp_setp.setText("%.1f" % temp_setp)
        pid.setpoint = temp_setp

    @QtCore.pyqtSlot()
    def process_qlin_pid_Kp(self):
        try:
            pid_Kp = float(self.qlin_pid_Kp.text())
        except (TypeError, ValueError):
            pid_Kp = 0
        except:
            raise

        pid_Kp = np.clip(pid_Kp, 0, 10)
        self.qlin_pid_Kp.setText("%.1f" % pid_Kp)
        pid.set_tunings(pid_Kp, pid.ki, pid.kd)

    @QtCore.pyqtSlot()
    def process_qlin_pid_Ki(self):
        try:
            pid_Ki = float(self.qlin_pid_Ki.text())
        except (TypeError, ValueError):
            pid_Ki = 0
        except:
            raise

        pid_Ki = np.clip(pid_Ki, 0, 1)
        self.qlin_pid_Ki.setText("%.0e" % pid_Ki)
        pid.set_tunings(pid.kp, pid_Ki, pid.kd)

    @QtCore.pyqtSlot()
    def process_qlin_pid_V_clamp(self):
        try:
            V_clamp = float(self.qlin_pid_V_clamp.text())
        except (TypeError, ValueError):
            V_clamp = PID_V_clamp
        except:
            raise

        V_CLAMP_MAX = 18  # [V]
        V_clamp = np.clip(V_clamp, 0, V_CLAMP_MAX)
        self.qlin_pid_V_clamp.setText("%.1f" % V_clamp)
        pid.set_output_limits(0, V_clamp)

    @QtCore.pyqtSlot()
    def update_GUI(self):
        str_cur_date, str_cur_time, _ = get_current_date_time()
        self.qlbl_cur_date_time.setText(
            "%s    %s" % (str_cur_date, str_cur_time)
        )
        self.qlbl_update_counter.setText("%i" % qdev_ard.update_counter_DAQ)
        self.qlbl_DAQ_rate.setText(
            "DAQ: %.1f Hz" % qdev_ard.obtained_DAQ_rate_Hz
        )
        if log.is_recording():
            self.qlbl_recording_time.setText(log.pretty_elapsed())

        self.qlin_dht22_temp.setText("%.2f" % state.dht22_temp)
        self.qlin_dht22_humi.setText("%.1f" % state.dht22_humi)
        self.qlin_power.setText("%.3f" % psu.state.P_meas)
        self.qlbl_title.setText(
            "Interior:  %.1f °C,  %.1f %%"
            % (state.dht22_temp, state.dht22_humi)
        )

        if state.pid_enabled:
            self.qpbt_pid_enabled.setChecked(True)
            self.qpbt_pid_enabled.setText("PID ON")
            qdev_psu.V_source.setText("%.3f" % pid.output)
        else:
            self.qpbt_pid_enabled.setChecked(False)
            self.qpbt_pid_enabled.setText("PID OFF")

    @QtCore.pyqtSlot()
    def update_chart(self):
        if DEBUG:
            tprint("update_chart")

        for tscurve in self.tscurves:
            tscurve.update()


# ------------------------------------------------------------------------------
#   Program termination routines
# ------------------------------------------------------------------------------


def stop_running():
    app.processEvents()
    qdev_ard.quit()
    qdev_psu.quit()
    log.close()

    print("Stopping timers................ ", end="")
    timer_GUI.stop()
    timer_charts.stop()
    print("done.")


@QtCore.pyqtSlot()
def notify_connection_lost():
    stop_running()

    window.qlbl_title.setText("! ! !    LOST CONNECTION    ! ! !")
    str_cur_date, str_cur_time, _ = get_current_date_time()
    str_msg = "%s %s\nLost connection to Arduino." % (
        str_cur_date,
        str_cur_time,
    )
    print("\nCRITICAL ERROR @ %s" % str_msg)
    reply = QtWid.QMessageBox.warning(
        window, "CRITICAL ERROR", str_msg, QtWid.QMessageBox.Ok
    )

    if reply == QtWid.QMessageBox.Ok:
        pass  # Leave the GUI open for read-only inspection by the user


@QtCore.pyqtSlot()
def about_to_quit():
    print("\nAbout to quit")
    stop_running()
    ard.close()


# ------------------------------------------------------------------------------
#   Your Arduino update function
# ------------------------------------------------------------------------------


def DAQ_function():
    # Date-time keeping
    str_cur_date, str_cur_time, str_cur_datetime = get_current_date_time()

    # Query the Arduino for its state
    success, tmp_state = ard.query_ascii_values("?", delimiter="\t")
    if not (success):
        dprint(
            "'%s' reports IOError @ %s %s"
            % (ard.name, str_cur_date, str_cur_time)
        )
        return False

    # Parse readings into separate state variables
    try:
        (
            state.time,
            state.dht22_temp,
            state.dht22_humi,
            ds18b20_temp,
        ) = tmp_state
        state.time /= 1000  # Arduino time, [msec] to [s]
    except Exception as err:
        pft(err, 3)
        dprint(
            "'%s' reports IOError @ %s %s"
            % (ard.name, str_cur_date, str_cur_time)
        )
        return False

    # Optional extra sensor to register the heater surface temperature
    # print("%.2f" % ds18b20_temp)

    # We will use PC time instead
    state.time = time.perf_counter()

    # PID control
    pid.set_mode(
        mode=(
            psu.state.ENA_output
            and state.pid_enabled
            and not np.isnan(state.dht22_temp)
        ),
        current_input=state.dht22_temp,
        current_output=psu.state.V_source,
    )

    if pid.compute(current_input=state.dht22_temp):
        # New PID output got computed -> send new voltage to PSU
        qdev_psu.send(qdev_psu.dev.set_V_source, pid.output)

        # Print debug info to the terminal
        dprint(
            "Tp=%7.3f   Ti=%7.3f   outp=%7.3f"
            % (pid.pTerm, pid.iTerm, pid.output)
        )

    # Add readings to chart histories
    window.tscurve_dht22_temp.appendData(state.time, state.dht22_temp)
    window.tscurve_dht22_humi.appendData(state.time, state.dht22_humi)
    window.tscurve_power.appendData(state.time, psu.state.P_meas)

    # Logging to file
    log.update(filepath=str_cur_datetime + ".txt", mode="w")

    # Return success
    return True


def write_header_to_log():
    log.write("[HEADER]\n")
    log.write(window.qtxt_comments.toPlainText())
    log.write("\n\n[DATA]\n")
    log.write("time\ttemperature\thumidity\theater power\n")
    log.write("[s]\t[±0.5 °C]\t[±3 pct]\t[±0.05 W]\n")


def write_data_to_log():
    log.write(
        "%.1f\t%.2f\t%.1f\t%.3f\n"
        % (log.elapsed(), state.dht22_temp, state.dht22_humi, psu.state.P_meas,)
    )


# ------------------------------------------------------------------------------
#   Main
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    # Set priority of this process to maximum in the operating system
    print("PID: %s\n" % os.getpid())
    try:
        proc = psutil.Process(os.getpid())
        if os.name == "nt":
            proc.nice(psutil.REALTIME_PRIORITY_CLASS)  # Windows
        else:
            proc.nice(-20)  # Other
    except:
        print("Warning: Could not set process to maximum priority.\n")

    # --------------------------------------------------------------------------
    #   Connect to devices
    # --------------------------------------------------------------------------

    # Arduino
    ard = Arduino(name="Ard", connect_to_specific_ID="E. coli sauna")
    ard.serial_settings["baudrate"] = 115200
    ard.auto_connect(filepath_last_known_port="config/port_Arduino.txt")

    if not (ard.is_alive):
        print("\nCheck connection and try resetting the Arduino.")
        print("Exiting...\n")
        sys.exit(0)

    # Power supply
    psu = Aim_TTi_PSU()
    if psu.auto_connect(filepath_last_known_port="config/port_PSU.txt"):
        psu.begin()

    # --------------------------------------------------------------------------
    #   Create application
    # --------------------------------------------------------------------------
    QtCore.QThread.currentThread().setObjectName("MAIN")  # For DEBUG info

    app = QtWid.QApplication(sys.argv)
    app.aboutToQuit.connect(about_to_quit)

    # --------------------------------------------------------------------------
    #   Set up multithreaded communication with the devices
    # --------------------------------------------------------------------------

    # Arduino
    qdev_ard = QDeviceIO(ard)
    qdev_ard.create_worker_DAQ(
        DAQ_function=DAQ_function,
        DAQ_interval_ms=DAQ_INTERVAL_MS,
        critical_not_alive_count=1,
        debug=DEBUG,
    )
    # Power supply
    qdev_psu = Aim_TTi_PSU_qdev(
        dev=psu, DAQ_interval_ms=200, critical_not_alive_count=3
    )

    # --------------------------------------------------------------------------
    #   Create GUI
    # --------------------------------------------------------------------------

    window = MainWindow()

    # Connect signals
    qdev_ard.signal_DAQ_updated.connect(window.update_GUI)
    qdev_ard.signal_connection_lost.connect(notify_connection_lost)

    # --------------------------------------------------------------------------
    #   File logger
    # --------------------------------------------------------------------------

    log = FileLogger(
        write_header_function=write_header_to_log,
        write_data_function=write_data_to_log,
    )
    log.signal_recording_started.connect(
        lambda filepath: window.qpbt_record.setText(
            "Recording to file: %s" % filepath
        )
    )
    log.signal_recording_stopped.connect(
        lambda: window.qpbt_record.setText("Click to start recording to file")
    )

    # --------------------------------------------------------------------------
    #   PID control
    # --------------------------------------------------------------------------
    #  process variable: PSU output voltage @ psu.state.V_source
    #  control variable: DHT22 temperature  @ state.dht21_temp

    pid = PID_Controller(Kp=PID_Kp, Ki=PID_Ki, Kd=0, debug=False)
    pid.setpoint = PID_TEMP_SETPOINT
    pid.set_output_limits(0, PID_V_clamp)

    # --------------------------------------------------------------------------
    #   Timers
    # --------------------------------------------------------------------------

    timer_GUI = QtCore.QTimer()
    timer_GUI.timeout.connect(window.update_GUI)
    timer_GUI.start(100)

    timer_charts = QtCore.QTimer()
    timer_charts.timeout.connect(window.update_chart)
    timer_charts.start(CHART_INTERVAL_MS)

    # --------------------------------------------------------------------------
    #   Start the main GUI event loop
    # --------------------------------------------------------------------------

    qdev_ard.start()
    qdev_psu.start()

    window.show()
    sys.exit(app.exec_())
