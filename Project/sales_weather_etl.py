from airflow import DAG
from airflow.operators.python_operator import PythonOperator
import logging
import requests
import pandas as pd
from pymongo import MongoClient
from datetime import datetime, timedelta

# Set up the MongoDB connection and sales data URL
MONGO_URI = "mongodb+srv://tsjannoun123:KufyyNNqnno0atX9@cluster0.sb8py.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
URL = 'https://raw.githubusercontent.com/DrManalJalloul/Introduction-to-Data-Engineering/main/sales_data.csv'
API_KEY = "3159ae9ae876db0990fa9835fbc288dc"  # OpenWeatherMap API Key

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_sales_data():
    """Extract sales data from the GitHub URL."""
    try:
        logging.info("Fetching sales data from GitHub...")
        sales_data = pd.read_csv(URL)
        logging.info(f"Sales data successfully loaded. Shape: {sales_data.shape}")
        return sales_data.to_dict()  # Convert DataFrame to dictionary for Airflow XComs
    except Exception as e:
        logging.error(f"Error while fetching sales data: {e}")
        raise

def fetch_weather_data(city):
    """Fetch weather data for the given city using OpenWeatherMap API."""
    try:
        logging.info(f"Fetching weather data for city: {city}")
        base_url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={API_KEY}"
        response = requests.get(base_url)
        data = response.json()

        if response.status_code != 200:
            logging.error(f"Failed to fetch weather data for {city}: {data.get('message', 'Unknown error')}")
            return None, None, None  # Return None values to avoid crashes

        # Extract relevant fields
        temperature = data['main']['temp'] - 273.15  # Convert from Kelvin to Celsius
        humidity = data['main']['humidity']
        weather_description = data['weather'][0]['description']

        logging.info(f"Weather data for {city}: {temperature}°C, {humidity}%, {weather_description}")
        return temperature, humidity, weather_description
    except Exception as e:
        logging.error(f"Error while fetching weather data for {city}: {e}")
        return None, None, None

def transform_and_load(**kwargs):
    """Transform sales data (add weather data) and load it into MongoDB."""
    try:
        ti = kwargs['ti']
        sales_data_dict = ti.xcom_pull(task_ids='extract_sales_data')

        if not sales_data_dict:
            logging.warning("No sales data received. Skipping transformation and loading.")
            return

        # Convert dictionary back to DataFrame
        sales_data = pd.DataFrame.from_dict(sales_data_dict)

        logging.info("Starting transformation process...")
        sales_data['Temperature'] = None
        sales_data['Humidity'] = None
        sales_data['Weather_Description'] = None

        for index, row in sales_data.iterrows():
            city = row['store_location']
            temp, hum, desc = fetch_weather_data(city)
            sales_data.at[index, 'Temperature'] = temp
            sales_data.at[index, 'Humidity'] = hum
            sales_data.at[index, 'Weather_Description'] = desc

        # Connect to MongoDB
        logging.info("Connecting to MongoDB...")
        client = MongoClient(MONGO_URI)
        db = client["Sales_Weather_DAG"]
        collection = db["Sales_Weather"]

        # Insert into MongoDB
        logging.info(f"Inserting {len(sales_data)} records into MongoDB...")
        collection.insert_many(sales_data.to_dict(orient='records'))
        logging.info("Sales and weather data successfully inserted into MongoDB")
    except Exception as e:
        logging.error(f"Error during transformation and loading: {e}")
        raise

# Airflow DAG setup
default_args = {
    'owner': 'airflow',
    'start_date': datetime(2025, 2, 8),
    'retries': 0,
    'retry_delay': timedelta(minutes=5)
}

dag = DAG(
    'sales_weather_etl',
    default_args=default_args,
    schedule_interval='0 6 * * *',
    catchup=False,
    max_active_runs=1
)

# Define Airflow tasks
extract_task = PythonOperator(
    task_id='extract_sales_data',
    python_callable=fetch_sales_data,
    dag=dag
)

transform_load_task = PythonOperator(
    task_id='transform_load_data',
    python_callable=transform_and_load,
    provide_context=True,
    dag=dag
)

# Task dependencies
extract_task >> transform_load_task

