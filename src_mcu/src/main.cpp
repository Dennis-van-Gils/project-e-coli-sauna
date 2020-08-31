/*******************************************************************************
  Temperature controlled box
  Adafruit ItsyBitsy M4

  Reads a DHT22 temperature and moisture sensor and reports the temperature
  [deg C] and relative humidity [%]. These temperature readings will be used to
  drive a PID controller running on a PC, and driving a digital power supply
  connected up to a resistive heater.

  The DHT22 temperature readings will be low-passed using an exponential filter:
    y(k) = a * y(k-1) +  (1-a) * x(k)

    where
    x(k) is the raw input at time step k
    y(k) is the filtered output at time step k
    a is a constant between 0 and 1, normally between 0.8 and 0.99.
    (a-1) or a is sometimes called the “smoothing constant”.

    For systems with a fixed time step T between samples, the constant “a”
    relates to the time constant tau:
    a = exp (-T/tau)            which is equivalent to tau = -T/ln(a)

  The RGB LED of the ItsyBitsy will indicate its status:
  * Blue : We're setting up
  * Green: Running okay
  * Red  : Error reading DHT22
  Every DHT read out, the LED will alternate in brightness high/low

  Dennis van Gils
  31-08-2020
*******************************************************************************/

#include <Arduino.h>
#include "DvG_SerialCommand.h"
#include "Adafruit_DotStar.h"

// DHT22
#include "DHT.h"
#define PIN_DHT 2
DHT dht(PIN_DHT, DHT22);

// Optional DS18B20 sensor
#include <OneWire.h>
#include <DallasTemperature.h>
#define PIN_DS18B20 9
OneWire oneWire(PIN_DS18B20);
DallasTemperature ds18b20(&oneWire);

// Instantiate serial command listener
DvG_SerialCommand sc(Serial);

// ItsyBitsy on-board RGB LED for error indication
#define RGB_LED_NUM_PIXELS 1
#define PIN_RGB_LED_DATA 8
#define PIN_RGB_LED_CLOCK 6
#define LED_DIM 50      // Brightness level for dim intensity [0 -255]
#define LED_BRIGHT 80   // Brightness level for bright intensity [0 -255]
Adafruit_DotStar strip(
    RGB_LED_NUM_PIXELS, PIN_RGB_LED_DATA, PIN_RGB_LED_CLOCK, DOTSTAR_BGR);

// Globals
#define UPDATE_PERIOD_MS 1000
float ds18b20_temp(NAN);  // Temperature       ['C]
float dht22_humi(NAN);    // Relative humidity [%]
float dht22_temp(NAN);    // Temperature       ['C]
float dht22_temp_smoothed(NAN); // Temperature ['C]

// Exponential smoothing factor
float a = 0.95;  // At 1 Hz this would indicate a time factor of ~20 sec

// -----------------------------------------------------------------------------
//    setup
// -----------------------------------------------------------------------------

void setup() {
    strip.begin();
    strip.setBrightness(LED_BRIGHT);
    strip.setPixelColor(0, 0, 0, 255); // Blue: We're in setup()
    strip.show();

    Serial.begin(9600);
    dht.begin();
    ds18b20.begin();

    strip.setPixelColor(0, 0, 255, 0); // Green: All set up
    strip.show();
}

// -----------------------------------------------------------------------------
//    loop
// -----------------------------------------------------------------------------

void loop() {
    char *strCmd; // Incoming serial command string
    uint32_t now = millis();
    static uint32_t tick = 0;
    static bool toggle = false;

    if (now - tick >= UPDATE_PERIOD_MS) {
        // The sensor will report the average temperature and humidity over 2
        // seconds. It's a slow sensor.
        tick = now;
        dht22_humi = dht.readHumidity();
        dht22_temp = dht.readTemperature();

        // Low-pass filter
        if (isnan(dht22_temp_smoothed)) {
            dht22_temp_smoothed = dht22_temp;
        } else {
            dht22_temp_smoothed = a * dht22_temp_smoothed + (1-a) * dht22_temp;
        }

        if (isnan(dht22_humi) || isnan(dht22_temp)) {
            strip.setPixelColor(0, 255, 0, 0); // Red: Error
        } else {
            strip.setPixelColor(0, 0, 255, 0); // Green: Okay
        }

        // Optional DS18B20 sensor
        ds18b20.requestTemperatures();
        ds18b20_temp = ds18b20.getTempCByIndex(0);

        if (ds18b20_temp < -126.0) {
            ds18b20_temp = NAN;
        }

        // Heartbeat LED
        if (toggle) {
            strip.setBrightness(LED_BRIGHT);
        } else {
            strip.setBrightness(LED_DIM);
        }
        strip.show();
        toggle = !toggle;
    }

    if (sc.available()) {
        strCmd = sc.getCmd();

        if (strcmp(strCmd, "id?") == 0) {
            Serial.println("Arduino, E. coli sauna");

        } else {
            Serial.println(
                String(tick) +
                '\t' + String(dht22_temp_smoothed, 3) +
                '\t' + String(dht22_humi, 1) +
                '\t' + String(ds18b20_temp, 2));
        }
    }
}
