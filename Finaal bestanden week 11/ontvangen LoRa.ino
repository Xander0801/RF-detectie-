#include <Wire.h>
#include <SPI.h>
#include <LoRa.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define LORA_SS   18
#define LORA_RST  23
#define LORA_DIO0 26
#define LORA_FREQ 868E6

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
    Serial.println("OLED init failed");
    while(true);
  }
  LoRa.setSpreadingFactor(7);  // meer gevoeligheid, minder data rate
  LoRa.setSignalBandwidth(250E3);
  LoRa.setCodingRate4(7);

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0,0);
  display.println("LoRa RX boot...");
  display.display();

  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI, LORA_SS);
  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);

  if(!LoRa.begin(LORA_FREQ)) {
    Serial.println("LoRa init failed");
    display.clearDisplay();
    display.setCursor(0,0);
    display.println("LoRa init failed!");
    display.display();
    while(true);
  }

  Serial.println("LoRa OK, wachten op JSON...");
  display.clearDisplay();
  display.setCursor(0,0);
  display.println("wachten op JSON...");
  display.display();
}

void loop() {
  int packetSize = LoRa.parsePacket();
  if(packetSize) {
    String msg = "";
    while(LoRa.available()) {
      msg += (char)LoRa.read();
    }
    msg.trim();

    // Print naar Serial
    Serial.print("Ontvangen JSON: ");
    Serial.println(msg);

    // Print naar OLED
    display.clearDisplay();
    display.setCursor(0,0);
    display.println("JSON ontvangen:");
    display.println(msg);
    display.display();
  }
}
