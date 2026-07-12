from flask import Flask, render_template, request
import psycopg2
import pandas as pd
import plotly.graph_objects as go
import threading
import time
from twilio.rest import Client
import keys  # Assuming keys.py contains your Twilio credentials
from sklearn.linear_model import LinearRegression
import numpy as np


app = Flask(__name__)

# Database connection parameters
CONNECTION = {
    'dbname': 'tsdb',
    'user': 'tsdbadmin',
    'password': 'h60vpq2gtlciio28',
    'host': 'wls9pfrz5j.px5bmnhsbk.tsdb.cloud.timescale.com',
    'port': '31081'
}

# Twilio client setup
client = Client(keys.account_sid, keys.auth_token)

def predict_future_values(model, X, num_steps=10):
    last_timestamp = X[-1]
    # Generate future timestamps in hourly intervals
    future_timestamps = np.arange(last_timestamp + 3600, last_timestamp + num_steps * 3600 + 3600, 3600)  # 3600 seconds = 1 hour
    future_X = future_timestamps.reshape(-1, 1)
    future_predictions = model.predict(future_X)
    return future_timestamps, future_predictions


def create_trend_analysis_figures(df, metric, num_future_steps=10):
    # Convert Timestamp to datetime and round to the nearest hour
    df['Timestamp'] = pd.to_datetime(df['Timestamp']).dt.floor('H')

    # Group by Timestamp to aggregate data if there are multiple entries per hour
    df_hourly = df.groupby('Timestamp').agg({
        'Water Level (m)': 'mean',
        'Temperature (°C)': 'mean',
        'Pressure (Pa)': 'mean'
    }).reset_index()

    # Prepare X for model training
    X = pd.to_datetime(df_hourly['Timestamp']).astype(int) / 10**9
    X = X.values.reshape(-1, 1)

    # Extracting the necessary columns
    if metric == 'Water Level (m)':
        y = df_hourly['Water Level (m)'].values
    elif metric == 'Temperature (°C)':
        y = df_hourly['Temperature (°C)'].values
    elif metric == 'Pressure (Pa)':
        y = df_hourly['Pressure (Pa)'].values
    else:
        raise ValueError("Unknown metric specified")

    # Fit a linear regression model
    model = LinearRegression().fit(X, y)
    trend_line = model.predict(X)

    # Predict future values
    future_timestamps, future_predictions = predict_future_values(model, X, num_future_steps)
    future_dates = pd.to_datetime(future_timestamps, unit='s')

    # Prepare figures
    trend_fig = go.Figure()

    # Add traces for historical data and trend line
    trend_fig.add_trace(go.Scatter(
        x=df_hourly['Timestamp'],
        y=y,
        mode='lines+markers',
        name=f'{metric} Data'
    ))
    trend_fig.add_trace(go.Scatter(
        x=df_hourly['Timestamp'],
        y=trend_line,
        mode='lines',
        name=f'{metric} Trend Line',
        line=dict(dash='dash')
    ))

    # Add traces for future predictions
    trend_fig.add_trace(go.Scatter(
        x=future_dates,
        y=future_predictions,
        mode='lines',
        name=f'{metric} Future Prediction',
        line=dict(dash='dot', color='red')
    ))

    trend_fig.update_layout(
        yaxis=dict(
            title='Value'
        ),
        xaxis=dict(
            title='Timestamp',
            tickformat='%Y-%m-%d %H:%M:%S',
            tickangle=-45
        ),
        title=f'Trend Analysis with Future Predictions for {metric}'
    )

    return trend_fig


# Function to send an alert via Twilio
def send_alert(alert, alert_type):
    client.messages.create(
        body=alert,
        from_=keys.twilio_number,
        to=keys.target_number
    )


# Function to monitor alerts
def monitor_alerts():
    sent_alerts = set()
    while True:
        # Fetch paginated data and alerts
        df, water_level_alerts, battery_level_alerts, null_value_alerts = fetch_paginated_data_and_alerts(100, 0,
                                                                                                          'dwlr')

        # Process water level alerts
        for alert in water_level_alerts:
            if alert not in sent_alerts:
                send_alert(alert, "Water Level")
                sent_alerts.add(alert)

        # Process battery level alerts
        for alert in battery_level_alerts:
            if alert not in sent_alerts:
                send_alert(alert, "Battery Level")
                sent_alerts.add(alert)

        # Process null value alerts
        for alert in null_value_alerts:
            if alert not in sent_alerts:
                send_alert(alert, "Null Value")
                sent_alerts.add(alert)

        # Sleep for a specified period before checking again
        time.sleep(60)  # Check every 60 seconds


# Function to fetch paginated data and generate alerts
def fetch_paginated_data_and_alerts(limit, offset, table_name, start_date=None, end_date=None):
    conn = psycopg2.connect(**CONNECTION)

    # Prepare date filters for SQL query
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND \"Timestamp\" BETWEEN '{start_date}' AND '{end_date}'"

    query = f"""
        SELECT * FROM {table_name}
        WHERE TRUE {date_filter}
        ORDER BY "Timestamp"
        LIMIT {limit} OFFSET {offset};
    """
    df = pd.read_sql(query, conn)
    conn.close()

    # Generate alerts based on water level, battery level, and null values
    water_level_alerts = []
    battery_level_alerts = []
    null_value_alerts = []

    for index, row in df.iterrows():
        if pd.isnull(row["Water Level (m)"]):
            null_value_alerts.append(f"Null Water Level at {row['Timestamp']}.")
        elif row["Water Level (m)"] < 3 or row["Water Level (m)"] >= 5:
            water_level_alerts.append(
                f"Critical Zone Alert at {row['Timestamp']}: Water level is {row['Water Level (m)']} meters.")

        if pd.isnull(row["Battery Level (%)"]):
            null_value_alerts.append(f"Null Battery Level at {row['Timestamp']}.")
        elif row["Battery Level (%)"] < 20:
            battery_level_alerts.append(
                f"Low Battery Alert at {row['Timestamp']}: Battery level is {row['Battery Level (%)']}%. Please charge the battery.")

    return df, water_level_alerts, battery_level_alerts, null_value_alerts


# Function to create figures with hover
def create_figures_with_hover(df):
    # Water Level Bar Chart
    water_level_colors = ['blue' if level >= 5 else 'green' for level in df['Water Level (m)']]

    bar_fig = go.Figure()
    bar_fig.add_trace(go.Bar(
        x=df['Timestamp'],
        y=df['Water Level (m)'],
        text=df['Water Level (m)'],
        marker_color=water_level_colors,
        name='Water Level (m)'
    ))
    bar_fig.update_layout(
        yaxis=dict(
            dtick=0.5,
            title='Water Level (m)',
            tickformat='.1f',
            range=[0, df['Water Level (m)'].max() + 1]
        ),
        xaxis=dict(
            title='Timestamp',
            tickformat='%Y-%m-%d %H:%M:%S',
            tickangle=-90,
            tickvals=df['Timestamp'],  # Ensure all timestamps are used for ticks
            ticktext=[ts.strftime('%Y-%m-%d %H:%M:%S') for ts in df['Timestamp']]  # Customize tick labels
        ),
        title='Water Level Bar Chart'
    )

    # Temperature Line Chart
    temp_fig = go.Figure()
    temp_fig.add_trace(go.Scatter(
        x=df['Timestamp'],
        y=df['Temperature (°C)'],
        mode='lines+markers',
        name='Temperature (°C)'
    ))
    temp_fig.update_layout(
        yaxis=dict(
            title='Temperature (°C)'
        ),
        xaxis=dict(
            title='Timestamp',
            tickformat='%Y-%m-%d %H:%M:%S',
            tickangle=-45
        ),
        title='Temperature Over Time'
    )

    # Pressure Bar Chart
    pressure_fig = go.Figure()
    pressure_fig.add_trace(go.Bar(
        x=df['Timestamp'],
        y=df['Pressure (Pa)'],
        name='Barometric Pressure(hPa)'
    ))
    pressure_fig.update_layout(
        yaxis=dict(
            title='Barometric Pressure(hPa)'
        ),
        xaxis=dict(
            title='Timestamp',
            tickformat='%Y-%m-%d %H:%M:%S',
            tickangle=-45
        ),
        title='Pressure Over Time'
    )

    # Z-Score Line Chart for Water Level
    z_scores_water_level = (df['Water Level (m)'] - df['Water Level (m)'].mean()) / df['Water Level (m)'].std()
    z_score_fig_water_level = go.Figure()
    z_score_fig_water_level.add_trace(go.Scatter(
        x=df['Timestamp'],
        y=z_scores_water_level,
        mode='lines+markers',
        name='Z-Score (Water Level)'
    ))
    z_score_fig_water_level.update_layout(
        yaxis=dict(
            title='Z-Score'
        ),
        xaxis=dict(
            title='Timestamp',
            tickformat='%Y-%m-%d %H:%M:%S',
            tickangle=-45
        ),
        title='Z-Score of Water Level'
    )

    # IQR Box Plot for Water Level
    iqr_fig_water_level = go.Figure()
    iqr_fig_water_level.add_trace(go.Box(
        y=df['Water Level (m)'],
        name='Water Level (m)',
        boxpoints='all',
        jitter=0.3,
        pointpos=-1.8
    ))
    iqr_fig_water_level.update_layout(
        yaxis=dict(
            title='Water Level (m)'
        ),
        xaxis=dict(
            title='Distribution'
        ),
        title='IQR of Water Level'
    )

    # Z-Score Line Chart for Temperature
    z_scores_temp = (df['Temperature (°C)'] - df['Temperature (°C)'].mean()) / df['Temperature (°C)'].std()
    z_score_fig_temp = go.Figure()
    z_score_fig_temp.add_trace(go.Scatter(
        x=df['Timestamp'],
        y=z_scores_temp,
        mode='lines+markers',
        name='Z-Score (Temperature)'
    ))
    z_score_fig_temp.update_layout(
        yaxis=dict(
            title='Z-Score'
        ),
        xaxis=dict(
            title='Timestamp',
            tickformat='%Y-%m-%d %H:%M:%S',
            tickangle=-45
        ),
        title='Z-Score of Temperature'
    )

    # IQR Box Plot for Temperature
    iqr_fig_temp = go.Figure()
    iqr_fig_temp.add_trace(go.Box(
        y=df['Temperature (°C)'],
        name='Temperature (°C)',
        boxpoints='all',
        jitter=0.3,
        pointpos=-1.8
    ))
    iqr_fig_temp.update_layout(
        yaxis=dict(
            title='Temperature (°C)'
        ),
        xaxis=dict(
            title='Distribution'
        ),
        title='IQR of Temperature'
    )

    # Z-Score Line Chart for Pressure
    z_scores_pressure = (df['Pressure (Pa)'] - df['Pressure (Pa)'].mean()) / df['Pressure (Pa)'].std()
    z_score_fig_pressure = go.Figure()
    z_score_fig_pressure.add_trace(go.Scatter(
        x=df['Timestamp'],
        y=z_scores_pressure,
        mode='lines+markers',
        name='Z-Score (Pressure)'
    ))
    z_score_fig_pressure.update_layout(
        yaxis=dict(
            title='Z-Score'
        ),
        xaxis=dict(
            title='Timestamp',
            tickformat='%Y-%m-%d %H:%M:%S',
            tickangle=-45
        ),
        title='Z-Score of Pressure'
    )

    # IQR Box Plot for Pressure
    iqr_fig_pressure = go.Figure()
    iqr_fig_pressure.add_trace(go.Box(
            y=df['Pressure (Pa)'],
        name='Barometric Pressure(hPa)',
        boxpoints='all',
        jitter=0.3,
        pointpos=-1.8
    ))
    iqr_fig_pressure.update_layout(
        yaxis=dict(
            title='Barometric Pressure(hPa)'
        ),
        xaxis=dict(
            title='Distribution'
        ),
        title='IQR of Pressure'
    )

    return bar_fig, temp_fig, pressure_fig, z_score_fig_water_level, iqr_fig_water_level, z_score_fig_temp, iqr_fig_temp, z_score_fig_pressure, iqr_fig_pressure



@app.route('/')
def index():
    metric = request.args.get('metric', 'water-level').lower()
    table_name = request.args.get('dwlr', 'dwlr')

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    df, water_level_alerts, battery_level_alerts,null_value_alerts = fetch_paginated_data_and_alerts(30, 0, table_name, start_date, end_date)

    # Update timestamps to hourly intervals and aggregate data
    df['Timestamp'] = pd.to_datetime(df['Timestamp']).dt.floor('H')

    # Create figures with hover
    bar_fig, temp_fig, pressure_fig, z_score_fig_water_level, iqr_fig_water_level, z_score_fig_temp, iqr_fig_temp, z_score_fig_pressure, iqr_fig_pressure = create_figures_with_hover(
        df)

    # Create trend analysis figures with predictions based on the selected metric
    if metric == 'water-level':
        trend_fig = create_trend_analysis_figures(df, 'Water Level (m)', num_future_steps=10)
        selected_graph_html = bar_fig.to_html(full_html=False)
        selected_z_score_html = z_score_fig_water_level.to_html(full_html=False)
        selected_iqr_html = iqr_fig_water_level.to_html(full_html=False)
    elif metric == 'temperature':
        trend_fig = create_trend_analysis_figures(df, 'Temperature (°C)', num_future_steps=10)
        selected_graph_html = temp_fig.to_html(full_html=False)
        selected_z_score_html = z_score_fig_temp.to_html(full_html=False)
        selected_iqr_html = iqr_fig_temp.to_html(full_html=False)
    elif metric == 'pressure':
        trend_fig = create_trend_analysis_figures(df, 'Pressure (Pa)', num_future_steps=10)
        selected_graph_html = pressure_fig.to_html(full_html=False)
        selected_z_score_html = z_score_fig_pressure.to_html(full_html=False)
        selected_iqr_html = iqr_fig_pressure.to_html(full_html=False)
    else:
        # Handle unknown metric gracefully
        trend_fig = create_trend_analysis_figures(df, 'Water Level (m)', num_future_steps=10)
        selected_graph_html = bar_fig.to_html(full_html=False)
        selected_z_score_html = z_score_fig_water_level.to_html(full_html=False)
        selected_iqr_html = iqr_fig_water_level.to_html(full_html=False)

    return render_template(
        'index.html',
        selected_graph_html=selected_graph_html,
        z_score_graph_html=selected_z_score_html,
        iqr_graph_html=selected_iqr_html,
        trend_graph_html=trend_fig.to_html(full_html=False),
        water_level_alerts=water_level_alerts,
        battery_level_alerts=battery_level_alerts,
        null_value_alerts = null_value_alerts,
        selected_metric=metric,
        start_date=start_date,
        end_date=end_date
    )



@app.route('/areas')
def areas():
    metric = request.args.get('metric', 'water-level').lower()
    table_name = request.args.get('dwlr', 'dwlr')
    city = request.args.get('city', '')

    # Handle optional date parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Fetch data
    df, water_level_alerts, battery_level_alerts,null_value_alerts = fetch_paginated_data_and_alerts(
        30, 0, table_name, start_date, end_date
    )

    df['Timestamp'] = pd.to_datetime(df['Timestamp']).dt.floor('H')

    # Create figures
    bar_fig, temp_fig, pressure_fig, z_score_fig_water_level, iqr_fig_water_level, z_score_fig_temp, iqr_fig_temp, z_score_fig_pressure, iqr_fig_pressure = create_figures_with_hover(df)

    if metric == 'water-level':
        trend_fig = create_trend_analysis_figures(df, 'Water Level (m)', num_future_steps=10)
        selected_graph_html = bar_fig.to_html(full_html=False)
        selected_z_score_html = z_score_fig_water_level.to_html(full_html=False)
        selected_iqr_html = iqr_fig_water_level.to_html(full_html=False)
    elif metric == 'temperature':
        trend_fig = create_trend_analysis_figures(df, 'Temperature (°C)', num_future_steps=10)
        selected_graph_html = temp_fig.to_html(full_html=False)
        selected_z_score_html = z_score_fig_temp.to_html(full_html=False)
        selected_iqr_html = iqr_fig_temp.to_html(full_html=False)
    elif metric == 'pressure':
        trend_fig = create_trend_analysis_figures(df, 'Pressure (Pa)', num_future_steps=10)
        selected_graph_html = pressure_fig.to_html(full_html=False)
        selected_z_score_html = z_score_fig_pressure.to_html(full_html=False)
        selected_iqr_html = iqr_fig_pressure.to_html(full_html=False)
    else:
        trend_fig = create_trend_analysis_figures(df, 'Water Level (m)', num_future_steps=10)
        selected_graph_html = bar_fig.to_html(full_html=False)
        selected_z_score_html = z_score_fig_water_level.to_html(full_html=False)
        selected_iqr_html = iqr_fig_water_level.to_html(full_html=False)

    # Return HTML for the charts and alerts
    return render_template(
        'areas.html',
        selected_graph_html=selected_graph_html,
        z_score_graph_html=selected_z_score_html,
        iqr_graph_html=selected_iqr_html,
        trend_graph_html=trend_fig.to_html(full_html=False),
        water_level_alerts=water_level_alerts,
        battery_level_alerts=battery_level_alerts
    )




if __name__ == '__main__':
    # Start the alert monitoring in a separate thread
    alert_thread = threading.Thread(target=monitor_alerts, daemon=True)
    alert_thread.start()

    app.run(debug=True)