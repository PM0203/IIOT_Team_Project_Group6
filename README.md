

🌡️ IIoT-Based Smart Humidity Control & Visualization Dashboard

Group 6 – MFG 598 | Arizona State University

Repository: https://github.com/PM0203/IIOT_Team_Project_Group6

An IIoT-based Smart Humidity Control System (IIoT Group6 project.pptx - for Full details)

This project demonstrates a fully integrated smart humidity control system that automates environmental monitoring and regulation using a complete IIoT architecture. The system uses two humidity/temperature sensors connected to a Raspberry Pi, which reads data, applies control logic, and communicates through the lightweight MQTT protocol. Data flows from the physical device layer to an edge-computing layer, then to a cloud platform consisting of Ignition and PostgreSQL, where real-time values, historical logs, and analytics are generated. A Streamlit-based dashboard visualizes live readings, actuator status, alerts, and trend analytics while also enabling remote manual control of the fan.

The project successfully demonstrates two way end-to-end IIoT functionality including sensing, communication, storage, visualization, and automated control while addressing real industrial needs such as stability, energy efficiency, and remote supervision. Despite challenges like sensor compatibility and USB hub control, the team built a robust data pipeline and control framework. Future extensions include scaling to multi-room environments, integrating predictive/AI-based control, adding OPC UA for industrial interoperability, and deploying cloud dashboards with automated alert systems.

⸻

⭐ Status

⸻

📌 Overview

This project demonstrates a complete IIoT ecosystem for humidity monitoring and automated control. Built using Raspberry Pi, MQTT, PostgreSQL, Python, and Streamlit, the system provides:
-	Real-time sensor monitoring
-	Edge computing
-	Cloud-ready communication
-	Historical logging
-	Control of actuators
-	Predictive analytics

This solution can be applied to labs, storage rooms, food processing, pharma, or any environment requiring controlled humidity.

⸻

🔧 System Architecture

⸻

Sensors → Raspberry Pi → MQTT → Logging → PostgreSQL → Streamlit → Control Server


<img width="735" height="394" alt="image" src="https://github.com/user-attachments/assets/b6f83316-f70c-4e19-98c6-2183d5bcec8d" />

⸻

🚀 Features

⸻

✔ Edge sensing (SenseHAT + EasyLog)

✔ MQTT telemetry

✔ JSON log storage

✔ PostgreSQL structured database

✔ Real-time Streamlit dashboard

✔ Forecasting (SES/DES/TES)

✔ Remote actuator control

✔ Modular, scalable architecture

⸻

⚙️ Installation & Setup

⸻

🥇 Setup Raspberry Pi

sudo apt update
sudo apt install python3-pip
sudo pip3 install paho-mqtt
sudo apt install chromium-browser
sudo apt install chromium-chromedriver

Clone the files in the folder: Raspi_Codes
- easylog_mqtt_pooler.py (This logs data from Easy Logg Sensor Through Webscraping stategy)
- publisher.py (This gets data from sense_hat)
- toggle_server.py (Acts as server and recieves communication through HTTP)
- toggle_usb.py (This is connected through the server to control the UCB Hub)

⸻

🥉 Setup the Laptop/Server

⸻

Install Python dependencies:

-    pip install -r requirements.txt

Install PostgreSQL:

-    pip install postgresql
-    pip services start postgresql

Environment Variables:

-    export PGHOST=localhost
-    export PGPORT=5432
-    export PGDATABASE=postgress
-    export PGUSER=postgres
-    export PGPASSWORD=admin

Create Tables:

CREATE TABLE "RAW DATA" (
    id SERIAL PRIMARY KEY,
    received_at TIMESTAMP,
    local_time TIMESTAMP,
    topic TEXT,
    qos INTEGER,
    retain BOOLEAN,
    payload TEXT
);

CREATE TABLE sensor_data (
    id SERIAL PRIMARY KEY,
    device_id TEXT NOT NULL,
    event_ts TIMESTAMP NOT NULL,
    temperature DOUBLE PRECISION,
    humidity DOUBLE PRECISION,
    source_file TEXT,          -- name of the log file the record came from
    source_line_no INTEGER     -- line number inside the log file
);

⸻

🖥 Start the System

⸻

On Raspberry Pi:

- python3 publisher.py
- python3 easylog_mqtt_pooler.py
- python3 toggle_server.py

Start Streamlit Dashboard:

streamlit run main_streamlit.py


⸻

🧪 Testing Guide

⸻

1. Change humidity physically

Sensor values update within seconds.

2. Check logs:

logs/YYYY-MM-DD/log_file.json

3. Check database:

SELECT * FROM "RAW DATA" ORDER BY timestamp DESC;

migration.py is responsible for moving parsed records from the "RAW DATA" table into the sensor_data table, converting raw MQTT payloads into structured, clean database entries used by the dashboard.

4. Test control from dashboard

Streamlit triggers URLs like:

http://<pi-ip>:8000/status

⸻

⚠️ Challenges & Solutions

⸻

• EasyLog compatibility issue

→ Solved using Python web scraping.

• USB port power switching

→ Solved using uhubctl.

• MQTT instability

→ Fixed through QoS tuning and retry logic.

• Time-series forecasting

→ Implemented SES, DES, and TES for smoothing.

⸻

🔮 Future Extensions

⸻

-	Multi-room, multi-sensor scalability
-	OPC-UA integration
-	AI-based auto-control
-	Cloud deployment
-	SMS/email alerts
-	Compliance-ready audit logging

⸻

👥 Authors (Group 6)

⸻
-	Hsin Cheng
-	Pankaj Mishra
-	Pratyodhaya Padalinathan


🎉 Summary

This repository contains a fully working IIoT system with sensing, communication, data logging, storage, forecasting, and control.
The provided instructions allow any user to replicate or extend the system.

