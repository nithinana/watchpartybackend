import eventlet
import socketio
import os
import time

# Initialize Socket.io server
sio = socketio.Server(cors_allowed_origins='*')
app = socketio.WSGIApp(sio)

# Room storage: 
# { 
#   room_id: { 
#       hosts: [sid1, sid2], 
#       movieUrl: str, 
#       users: [{id, name}],
#       current_state: 'pause',
#       last_recorded_time: 0.0,
#       last_update_timestamp: time.time()
#   } 
# }
rooms = {}

@sio.event
def connect(sid, environ):
    print(f"User connected: {sid}")

@sio.on('create-room')
def on_create(sid, data):
    room_id = data['roomId']
    host_name = data['hostName']
    movie_url = data['movieUrl']
    
    sio.enter_room(sid, room_id)
    rooms[room_id] = {
        'hosts': [sid], # List of host SIDs
        'movieUrl': movie_url,
        'users': [{'id': sid, 'name': host_name}],
        'current_state': 'pause',
        'last_recorded_time': 0.0,
        'last_update_timestamp': time.time()
    }
    sio.emit('room-created', room_id, room=sid)
    sio.emit('you-are-host', room=sid)
    print(f"Room {room_id} created by {host_name}")

@sio.on('join-room')
def on_join(sid, data):
    room_id = data['roomId']
    user_name = data['userName']
    
    if room_id in rooms:
        sio.enter_room(sid, room_id)
        
        # Add user to list
        rooms[room_id]['users'].append({'id': sid, 'name': user_name})
        
        # Broadcast new user list
        sio.emit('user-list', rooms[room_id]['users'], room=room_id)
        
        # Calculate current video time based on server state
        room = rooms[room_id]
        current_video_time = room['last_recorded_time']
        
        # If playing, add the elapsed time since the last update
        if room['current_state'] == 'play':
            time_diff = time.time() - room['last_update_timestamp']
            current_video_time += time_diff

        # Send join info + immediate sync data
        sio.emit('joined-room', {
            'movieUrl': room['movieUrl'],
            'startTime': current_video_time,
            'state': room['current_state'],
            'isHost': (sid in room['hosts'])
        }, room=sid)
    else:
        sio.emit('error', 'Room not found', room=sid)

@sio.on('sync-video')
def on_sync(sid, data):
    room_id = data['roomId']
    if room_id in rooms:
        # Check if user is one of the hosts
        if sid in rooms[room_id]['hosts']:
            # Update server state
            rooms[room_id]['current_state'] = data['state']
            rooms[room_id]['last_recorded_time'] = data['time']
            rooms[room_id]['last_update_timestamp'] = time.time()

            # Broadcast to others
            sio.emit('video-update', {
                'state': data['state'],
                'time': data['time']
            }, room=room_id, skip_sid=sid)

@sio.on('promote-host')
def on_promote(sid, data):
    room_id = data['roomId']
    target_id = data['targetId']
    
    if room_id in rooms and sid in rooms[room_id]['hosts']:
        if target_id not in rooms[room_id]['hosts']:
            rooms[room_id]['hosts'].append(target_id)
            sio.emit('you-are-host', room=target_id)
            # Refresh user list so UI updates (crown icons etc)
            sio.emit('user-list', rooms[room_id]['users'], room=room_id)

@sio.on('stop-party')
def on_stop(sid, room_id):
    if room_id in rooms and sid in rooms[room_id]['hosts']:
        sio.emit('party-ended', room=room_id)
        del rooms[room_id]

@sio.event
def disconnect(sid):
    print(f"User disconnected: {sid}")
    # Search all rooms to remove the user
    # Note: iterating copy of keys to avoid runtime error if we delete
    for room_id in list(rooms.keys()):
        room = rooms[room_id]
        
        # Check if user is in this room
        user_in_room = next((u for u in room['users'] if u['id'] == sid), None)
        
        if user_in_room:
            # Remove from users list
            room['users'] = [u for u in room['users'] if u['id'] != sid]
            
            # Remove from hosts list if present
            if sid in room['hosts']:
                room['hosts'].remove(sid)
            
            # If room is empty, delete it
            if not room['users']:
                del rooms[room_id]
            else:
                # If no hosts left, maybe assign the first person? 
                # For now, we'll leave it leaderless or let original hosts persist
                if not room['hosts'] and room['users']:
                    new_host = room['users'][0]['id']
                    room['hosts'].append(new_host)
                    sio.emit('you-are-host', room=new_host)

                # Broadcast updated list to remaining users
                sio.emit('user-list', room['users'], room=room_id)
            
            break # User can only be in one room in this app logic

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
