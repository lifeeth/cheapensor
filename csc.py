import bluetooth
import struct
import time
from ble_advertising import advertising_payload

from micropython import const

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_INDICATE_DONE = const(20)

# CSC service
_CSC_SERVICE_UUID=bluetooth.UUID(0x1816)
# CSC Feature Characteristic
_CSC_FEATURE_CHAR = (
    bluetooth.UUID(0x2A5C),
    bluetooth.FLAG_READ,
)
# CSC Measurement Characteristic
_CSC_MEASUREMENT_CHAR = (
    bluetooth.UUID(0x2A5B),
    bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY,
)

# We only plan to have these two features
_CSC_FEATURE_WHEEL_REV_DATA=0x01
_CSC_FEATURE_CRANK_REV_DATA=0x02

_CSC_FEATURES = _CSC_FEATURE_WHEEL_REV_DATA | _CSC_FEATURE_CRANK_REV_DATA

_CSC_SERVICE = (
    _CSC_SERVICE_UUID,
    (_CSC_FEATURE_CHAR,_CSC_MEASUREMENT_CHAR),
)

# org.bluetooth.characteristic.gap.appearance.xml for cadence sensor
_ADV_APPEARANCE_CYCLING_SPEED_CADENCE_SENSOR = const(1157)

class BLECycling:
    def __init__(self, ble, name="cheapensor", debug=False):
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(handler=self._irq)
        ((self._handle_feature,self._handle_measurement,),) = self._ble.gatts_register_services((_CSC_SERVICE,))
        self._connections = set()
        self._payload = advertising_payload(
            name=name, services=[_CSC_SERVICE_UUID], appearance=_ADV_APPEARANCE_CYCLING_SPEED_CADENCE_SENSOR
        )
        # Write the feature
        self._ble.gatts_write(self._handle_feature, struct.pack("<h", _CSC_FEATURES))
        self._advertise()

        self._cumulative_wheel_revolutions=0
        self._last_wheel_event_time=0
        self._cumulative_crank_revolutions=0
        self._last_crank_event_time=0

        self._debug=debug

    def _send_measurement(self):
        # Measurement
        # Byte 0 is CSC Feature
        # Byte 1 to 4 are cumulative_wheel_revolutions
        # Byte 5,6 are last_wheel_event_time
        # Byte 7,8 are cumulative_crank_revolutions
        # Bytw 9,10 are last_crank_event_time
        _measurement=bytearray(11)
        _measurement[0]=_CSC_FEATURES
        # Pack into unsigned int - little-endian
        _measurement[1:5]=struct.pack("<I",self._cumulative_wheel_revolutions)
        # 1 second = 1024 for the event time as per CSC spec
        _measurement[5:7]=struct.pack("<H",int(self._last_wheel_event_time*1.024))
        _measurement[7:9]=struct.pack("<H",self._cumulative_crank_revolutions)
        # 1 second = 1024 for the event time as per CSC spec
        _measurement[9:]=struct.pack("<H",int(self._last_crank_event_time*1.024))
        for conn_handle in self._connections:
            # Notify connected centrals.
            self._ble.gatts_notify(conn_handle, self._handle_measurement, _measurement)

        if self._debug:
            print(self._cumulative_wheel_revolutions)
            print(self._last_wheel_event_time)
            print(self._cumulative_crank_revolutions)
            print(self._last_crank_event_time)
            print(_measurement)

    def wheel_event(self):
        self._last_wheel_event_time=time.ticks_ms()
        self._cumulative_wheel_revolutions+=1
        # Send the measurement out
        self._send_measurement()

    def crank_event(self):
        self._last_crank_event_time=time.ticks_ms()
        self._cumulative_crank_revolutions+=1
        # Send the measurement out
        self._send_measurement()

    def _irq(self, event, data):
        # Track connections so we can send notifications.
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _, = data
            self._connections.add(conn_handle)
            print("Someone connected")
            # Start advertising again to allow a new connection.
            self._advertise()
        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _, = data
            self._connections.remove(conn_handle)
            print("Someone disconnected")
            # Start advertising again to allow a new connection.
            self._advertise()
        elif event == _IRQ_GATTS_INDICATE_DONE:
            conn_handle, value_handle, status, = data

    def _advertise(self, interval_us=500000):
        self._ble.gap_advertise(interval_us, adv_data=self._payload)

def activate(debug=False):
    ble = bluetooth.BLE()
    csc = BLECycling(ble,debug=debug)
    while True:
        time.sleep_ms(1000)
        csc.wheel_event()
        csc.crank_event()
