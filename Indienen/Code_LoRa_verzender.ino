#include <Wire.h>
#include <SPI.h>
#include <LoRa.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// --- LoRa pinout LilyGO T3 V1.6.1 ---
#define LORA_SS   18
#define LORA_RST  23
#define LORA_DIO0 26
#define LORA_FREQ 868E6   // EU

#define SPI_SCK  5
#define SPI_MISO 19
#define SPI_MOSI 27

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define SDA_PIN 21
#define SCL_PIN 22

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

void setup() {
  Serial.begin(115200);

  Wire.begin(SDA_PIN, SCL_PIN);
  if(!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED error");
    while(1);
  }

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0,0);
  display.println("LoRa TX boot...");
  display.display();

  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI, LORA_SS);
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);

  if (!LoRa.begin(LORA_FREQ)) {
    Serial.println("LoRa init failed!");
    display.clearDisplay();
    display.setCursor(0,0);
    display.println("LoRa init failed!");
    display.display();
    while (1);
  }

  // Hierdoor gebruik je weer exact dezelfde instellingen als toen het wél werkte.

  Serial.println("LoRa OK, klaar om JSON te verzenden");
  display.clearDisplay();
  display.setCursor(0,0);
  display.println("Wachten op seriële data...");
  display.display();
}

void loop() {
  if (Serial.available()) {
    String json = Serial.readStringUntil('\n');
    json.trim();

    display.clearDisplay();
    display.setCursor(0,0);
    display.println("Verzenden JSON:");
    display.println(json);
    display.display();

    LoRa.beginPacket();
    LoRa.print(json);
    LoRa.endPacket();

    Serial.print("Verzonden via LoRa: ");
    Serial.println(json);
  }
}
