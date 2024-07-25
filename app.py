import os
import json
import sqlite3
import logging
import subprocess
from preston import Preston
from datetime import datetime
from flask import Flask, redirect, request, session, url_for, render_template, jsonify
import asyncio
import aiohttp
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Load configuration
with open('config.json') as config_file:
    config = json.load(config_file)

app = Flask(__name__)

preston = Preston(
    user_agent= config['user_agent'],
    client_id= config['client_id'],
    client_secret= config['client_secret'],
    callback_url= config['redirect_uri'],
    scope= config['scopes']
)
# Database setup
DATABASE = 'eve_auth.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS characters (
                        id INTEGER PRIMARY KEY,
                        character_id TEXT NOT NULL,
                        character_name TEXT NOT NULL,
                        refresh_token TEXT NOT NULL,
                        location TEXT,
                        last_updated TEXT,
                        ship TEXT
                      )''')
    conn.commit()
    conn.close()

@app.before_request
def before_request():
    if not os.path.exists(DATABASE):
        init_db()

@app.route('/launch_character', methods=['POST'])
def launch_character():
    data = request.get_json()
    character_name = data.get('character')
    if not character_name:
        return jsonify({"error": "Character name is required"}), 400

    try:
        subprocess.Popen(['python', 'launch.py', character_name])
        return jsonify({"message": f"Launching character: {character_name}"}), 200
    except Exception as e:
        logging.error(f"Error launching character: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def index():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT character_id, character_name, location, ship FROM characters')
    characters = cursor.fetchall()
    conn.close()
    
    characters = [(c[0], c[1], json.loads(c[2]) if c[2] else None, c[3]) for c in characters]
    
    return render_template('index.html', characters=characters)

@app.route('/login')
def login():
    authorization_url = preston.get_authorize_url()
    logging.debug(f'Authorization URL: {authorization_url}')
    return redirect(authorization_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    auth = preston.authenticate(code)

    character_info = auth.whoami()
    logging.debug(f'char info: {character_info}')
    token = auth.refresh_token
    
    logging.debug(f'token info: {auth.refresh_token}')
    logging.debug(f'token info: {auth.access_token}')

    character_id = character_info['CharacterID']
    character_name = character_info['CharacterName']
    expires_on = character_info['ExpiresOn']

    # Store in the database
    conn = get_db()
    cursor = conn.cursor()
    # Check if the character_id already exists
    cursor.execute('SELECT id FROM characters WHERE character_id = ?', (character_id,))
    result = cursor.fetchone()

    if result:
        # Update the existing record
        cursor.execute('''UPDATE characters SET 
                            refresh_token = ?
                          WHERE character_id = ?''',
                       (auth.refresh_token, character_id))
        logging.debug(f'Updated character {character_name} in the database.')
    else:
        # Insert new record
        cursor.execute('INSERT INTO characters (character_id, character_name, refresh_token) VALUES (?, ?, ?)',
                       (character_id, character_name, auth.refresh_token))
        logging.debug(f'Inserted character {character_name} into the database.')

    conn.commit()
    conn.close()

    return redirect(url_for('index'))


def refresh_and_get_location_sync(character):
    refresh_token = character[0]
    authd = Preston(
                user_agent=config['user_agent'],
                client_id=config['client_id'],
                client_secret=config['client_secret'],
                callback_url=config['redirect_uri'],
                scope=config['scopes'],
                refresh_token=refresh_token
        )

    who_ami = authd.whoami()
    r_token = authd.refresh_token

    location = authd.get_op('get_characters_character_id_location', character_id=who_ami['CharacterID'])
    sysid = location['solar_system_id']
    struct_id = location.get('structure_id')
    if 'structure_id' not in location:
        try:
            structid = location['station_id']
            location['structure_name'] = authd.get_op('get_universe_stations_station_id', station_id=structid)['name']
        except:
            location['structure_name'] = "In Space"

    if struct_id:
        try:
            structid = location['structure_id']
            location['structure_name'] = authd.get_op('get_universe_structures_structure_id', structure_id=structid)['name']
        except:
            location['structure_name'] = "Docked: Docking Revoked"
    
    location['solar_system_name'] = authd.get_op('get_universe_systems_system_id', system_id=sysid)['name']
    ship_id = authd.get_op('get_characters_character_id_ship', character_id=who_ami['CharacterID'])
    shipID = ship_id['ship_type_id'] + 0
    ship = authd.get_op('get_universe_types_type_id', type_id=shipID)
    ship_name = ship['name']

    conn = get_db()
    cursor = conn.cursor()
    current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''UPDATE characters SET character_id = ?, character_name = ?, refresh_token = ?, location = ?, last_updated = ?, ship = ? WHERE character_id = ?''',
                    (who_ami['CharacterID'], who_ami['CharacterName'], r_token, json.dumps(location), current_time, ship_name, who_ami['CharacterID']))
    conn.commit()
    conn.close()
    return

@app.route('/refresh_and_get_location')
async def refresh_and_get_location():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT refresh_token FROM characters')
    characters = cursor.fetchall()
    conn.close()

    with ProcessPoolExecutor() as executor:
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(executor, refresh_and_get_location_sync, character)
            for character in characters
        ]
        await asyncio.gather(*tasks)

    return redirect("/", code=302)

@app.route('/desto')
def desto():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT character_id, character_name, location, ship FROM characters')
    characters = cursor.fetchall()
    conn.close()
    
    characters = [(c[0], c[1], json.loads(c[2]) if c[2] else None, c[3]) for c in characters]
    
    return render_template('base.html', characters=characters)

def refresh_token_if_needed(preston_params):
    user_agent, client_id, client_secret, callback_url, scope, refresh_token = preston_params
    
    preston = Preston(
        user_agent=user_agent,
        client_id=client_id,
        client_secret=client_secret,
        callback_url=callback_url,
        scope=scope,
        refresh_token=refresh_token
    )

    if preston._is_access_token_expired():
        preston._try_refresh_access_token()
    return preston

@app.route('/set_desto', methods=['POST'])
async def set_desto():
    if request.method == 'POST':
        system = request.form['button_value']

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT refresh_token FROM characters')
        characters = cursor.fetchall()
        conn.close()

        preston_params_list = [
            (
                config['user_agent'],
                config['client_id'],
                config['client_secret'],
                config['redirect_uri'],
                config['scopes'],
                character[0]  # Assuming fetchall() returns a list of tuples
            )
            for character in characters
        ]

        # Refresh tokens concurrently using ProcessPoolExecutor
        with ProcessPoolExecutor() as executor:
            loop = asyncio.get_running_loop()
            refresh_tasks = [
                loop.run_in_executor(executor, refresh_token_if_needed, params)
                for params in preston_params_list
            ]
            prestons = await asyncio.gather(*refresh_tasks)

        bg_tasks = [
            asyncio.create_task(main(preston, system))
            for preston in prestons
        ]

        await asyncio.gather(*bg_tasks)

    return redirect("/desto", code=302)

async def main(preston, system):
    async with aiohttp.ClientSession() as session:
        headers = preston.session.headers
        test = {"add_to_beginning": "true", "clear_other_waypoints": "true", "destination_id": system}

        async with session.post('https://esi.evetech.net/v2/ui/autopilot/waypoint/', headers=headers, params=test) as resp:
            print(resp.status)
            print(await resp.text())

@app.route('/isk', methods=['GET', 'POST'])
def isk():
    result = None
    if request.method == 'POST':
        text_data = request.form['text_data']
        result = calculate_isk_per_hour(text_data)
        print(result)
    
    return render_template('isk.html', result=result)

def calculate_isk_per_hour(text_data):
    lines = text_data.strip().split('\n')
    data = []
    total_isk = 0

    for line in lines:
        parts = line.split('\t')
        date_str = parts[0]
        amount_str = parts[2].replace(' ISK', '').replace(',', '')
        date = datetime.strptime(date_str, "%Y.%m.%d %H:%M")
        amount = int(amount_str) * 15  # Multiply by 15
        data.append((date, amount))
        total_isk = total_isk + amount

    # Reverse the data to have the earliest date first
    data.reverse()

    sessions = []
    session_start = data[0][0]
    session_end = data[0][0]
    session_isk = data[0][1]
    session_time = 0
    last_time = data[0][0]

    for i in range(1, len(data)):
        current_time = data[i][0]
        time_diff = (current_time - last_time).total_seconds() / 3600  # time diff in hours

        if time_diff <= 3:
            session_isk += data[i][1]
            session_time += time_diff
            session_end = current_time
        else:
            if session_time > 0:
                isk_per_hour = session_isk / session_time if session_time > 0 else 0
                sessions.append((session_start, session_end, int(isk_per_hour), format_large_number(session_isk)))
                print({session_start, session_end, int(isk_per_hour), int(time_diff/3600)})
            session_start = current_time
            session_end = current_time
            session_isk = data[i][1]
            session_time = 0  # Reset session time for new session
        
        last_time = current_time

    if session_time > 0:
        isk_per_hour = session_isk / session_time if session_time > 0 else 0
        time_diff = 0
        sessions.append((session_start, session_end, int(isk_per_hour), format_large_number(session_isk)))
    
    print(total_isk)

    return {
        'sessions': sessions,
        'totalisk': total_isk
    }
    
def format_large_number(value):
    # Define suffixes
    suffixes = ['', 'K', 'M', 'B', 'T']
    magnitude = 0
    
    # Convert the number to a float and keep reducing it by 1000 until it's less than 1000
    while abs(value) >= 1000:
        magnitude += 1
        value /= 1000.0
    
    # Return the formatted number with the appropriate suffix
    return f'{value:.2f}{suffixes[magnitude]}'

@app.route('/get_wallet', methods=['GET', 'POST'])
def get_wallet(refresh):
    refresh = refresh
    
    preston = Preston(
        
    )

if __name__ == "__main__":
    app.run(debug=True)