import eventlet
eventlet.monkey_patch()

import socketio
import string
import random
from flask import Flask
from flask_cors import CORS

eventlet.monkey_patch()

sio = socketio.Server(async_mode='eventlet', cors_allowed_origins="*")
app = Flask(__name__)
CORS(app)
app.wsgi_app = socketio.WSGIApp(sio, app.wsgi_app)

parties = {}

@sio.event
def connect(sid, environ):
    print(f'User connected: {sid}')

# NEW: Handler to check if a party code is valid
@sio.on('check_party_code')
def check_party_code(sid, data):
    party_code = data.get('partyCode')
    if party_code in parties:
        sio.emit('party_code_valid', to=sid)
    else:
        sio.emit('invalid_party_code', to=sid)
    print(f"User {sid} checked party code '{party_code}'.")

@sio.on('create_party')
def create_party(sid, data):
    party_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    sio.enter_room(sid, party_code)
    
    parties[party_code] = {
        'host_sid': sid,
        'movie_url': data.get('movieUrl'),
        'users': [{'id': sid, 'username': data.get('username'), 'isHost': True}],
        # NEW: Store the initial playback state
        'playback_state': {'time': 0, 'paused': True}
    }
    
    sio.emit('party_created', {
        'partyCode': party_code,
        'users': parties[party_code]['users']
    }, to=sid)
    print(f"Party '{party_code}' created by {sid}.")

# NEW: Handler for the host's periodic state updates
@sio.on('state_update')
def state_update(sid, data):
    """Receives state from host and stores it, then relays it for resyncing."""
    party_code = None
    for code, party_data in parties.items():
        if party_data.get('host_sid') == sid:
            party_code = code
            break
            
    if party_code:
        # Store the latest state from the host
        parties[party_code]['playback_state'] = data
        # Relay this state to other participants for periodic resyncing
        sio.emit('resync', data, to=party_code, skip_sid=sid)

@sio.on('join_party')
def join_party(sid, data):
    party_code = data.get('partyCode')
    username = data.get('username')
    
    if party_code in parties:
        sio.enter_room(sid, party_code)
        parties[party_code]['users'].append({'id': sid, 'username': username, 'isHost': False})
        
        # MODIFIED: Send the current playback state for initial sync
        sio.emit('join_success', {
            'partyCode': party_code,
            'movieUrl': parties[party_code]['movie_url'],
            'initialState': parties[party_code]['playback_state'] # Send host's current state
        }, to=sid)
        
        sio.emit('user_list_update', {'users': parties[party_code]['users']}, to=party_code)
        print(f"User {sid} ({username}) joined party '{party_code}'.")
    else:
        # Changed the event name to match what the client-side code is expecting
        sio.emit('invalid_party_code', to=sid)
        print(f"User {sid} failed to join invalid party '{party_code}'.")


@sio.on('disconnect')
def disconnect(sid):
    print(f'User disconnected: {sid}')
    party_code_to_update = None
    
    for code, party_data in parties.items():
        if any(user['id'] == sid for user in party_data['users']):
            party_code_to_update = code
            break
            
    if party_code_to_update and party_code_to_update in parties:
        party = parties[party_code_to_update]
        if party['host_sid'] == sid:
            sio.emit('party_ended', to=party_code_to_update)
            del parties[party_code_to_update]
            print(f"Host disconnected. Party '{party_code_to_update}' has been ended.")
        else:
            party['users'] = [user for user in party['users'] if user['id'] != sid]
            sio.emit('user_list_update', {'users': party['users']}, to=party_code_to_update)
            print(f"User {sid} left party '{party_code_to_update}'. User list updated.")

# These handlers are no longer needed as the logic is combined in state_update
# @sio.on('playback_action')
# def playback_action(sid, data): ...
@sio.on('end_party')
def end_party(sid):
    # ... (same as before, no changes needed here)
    party_code = None
    for code, party_data in parties.items():
        if party_data['host_sid'] == sid:
            party_code = code
            break
    if party_code:
        sio.emit('party_ended', to=party_code)
        del parties[party_code]
        print(f"Party '{party_code}' ended by host {sid}.")


if __name__ == '__main__':
    host = "localhost"
    port = 5000
    print(f"Starting server on http://{host}:{port}")
    eventlet.wsgi.server(eventlet.listen((host, port)), app)

