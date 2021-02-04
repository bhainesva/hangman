import asyncio
import sys

from google.protobuf.json_format import MessageToJson

import argparse
import logging
import os

import appdirs

import hangups
from sanic import Sanic
from sanic.response import html, json, raw

import socketio


def _get_parser():
    """Return ArgumentParser with any extra arguments."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    dirs = appdirs.AppDirs('hangups', 'hangups')
    default_token_path = os.path.join(dirs.user_cache_dir, 'refresh_token.txt')
    parser.add_argument(
        '--token-path', default=default_token_path,
        help='path used to store OAuth refresh token'
    )
    parser.add_argument(
        '-d', '--debug', action='store_true',
        help='log detailed debugging messages'
    )
    return parser

args = _get_parser().parse_args()
logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
# Obtain hangups authentication cookies, prompting for credentials from
# standard input if necessary.
cookies = hangups.auth.get_auth_stdin(args.token_path)
client = hangups.Client(cookies)
userlist = None
convList = None

async def sync_recent_conversations(client, _):
    user_list, conversation_list = (
        await hangups.build_user_conversation_list(client)
    )
    all_users = user_list.get_all()
    all_conversations = conversation_list.get_all(include_archived=True)

    print('{} known users'.format(len(all_users)))
    for user in all_users:
        print('    {}: {}'.format(user.full_name, user.id_.gaia_id))

sio = socketio.AsyncServer(async_mode='sanic', cors_allowed_origins="http://localhost:3000")
app = Sanic()
sio.attach(app)

async def on_hangups_event(conv_event):
    if isinstance(conv_event, hangups.ChatMessageEvent):
        print('received chat message: {!r}'.format(conv_event.text))
        await sio.emit('chat_message', conv_event._event.SerializeToString())

async def background_task():
    """Example of how to send server generated events to clients."""
    user_list, conv_list = (
        await hangups.build_user_conversation_list(client)
    )
    conv_list.on_event.add_observer(on_hangups_event)

    while True:
        await sio.sleep(5)


@app.listener('before_server_start')
async def before_server_start(sanic, loop):
    task = asyncio.ensure_future(client.connect())

    # Wait for hangups to either finish connecting or raise an exception.
    on_connect = asyncio.Future()
    client.on_connect.add_observer(lambda: on_connect.set_result(None))
    done, _ = await asyncio.wait(
        (on_connect, task), return_when=asyncio.FIRST_COMPLETED
    )
    await asyncio.gather(*done)
    sio.start_background_task(background_task)

def minConversation(conv):
    return {
        'id': conv.id_,
        'name': conv.name,
        'users': conv.users,
        'last_modified': conv.last_modified,
    }

@app.route('/')
async def index(request):
    with open('app.html') as f:
        return html(f.read())

@app.route('/api/conversations')
async def index(request):
    global convList

    if convList:
        return json(list(map(minConversation, convList.get_all(include_archived=True))), headers={'Access-Control-Allow-Origin': 'http://localhost:3000'})

    user_list, conversation_list = (
        await hangups.build_user_conversation_list(client)
    )

    convList = conversation_list
    return json(list(map(minConversation, convList.get_all(include_archived=True))), headers={'Access-Control-Allow-Origin': 'http://localhost:3000'})

def copyConvState(cState):
    new_state = hangups.hangouts_pb2.ConversationState()
    new_state.conversation_id.id = cState.conversation_id.id
    print("setting it to: ", cState.conversation_id.id)
    for event in cState.event:
        new_event = hangups.hangouts_pb2.Event()
        new_event.conversation_id.id = event.conversation_id.id
        new_event.sender_id.CopyFrom(event.sender_id)
        new_event.timestamp = event.timestamp
        new_event.source_type = event.source_type
        new_event.chat_message.CopyFrom(event.chat_message)
        new_event.hangout_event.CopyFrom(event.hangout_event)
        new_event.event_id = event.event_id

        new_state.event.append(new_event)

    return new_state

@app.route('/api/conversations/<id>')
async def conversation_handler(request, id):
    conv = convList.get(id)
    await conv.get_events(conv.events[0].id_)
    convState = hangups.hangouts_pb2.ConversationState()
    events = await conv.get_events(max_events=10)
    # convState.event.extend(list(map(lambda e: e._event, events)))
    convState.event.append(events[0]._event)
    # convState.conversation_id.id = conv.id_
    print(convState.SerializeToString().hex())
    print('------------------------------------------')
    print(convState)

    # print('------------------------------------------')
    # print(" ".join(map(lambda x: str(x), s)))
    # for char in s:
    #     print(char)
        # print(int.from_bytes(char, byteorder=sys.byteorder))
    print('------------------------------------------')
    return raw(copyConvState(convState).SerializeToString(), headers={'Access-Control-Allow-Origin': 'http://localhost:3000'})

@app.route('/api/users')
async def index(request):
    global userlist

    if userlist:
        return json(userlist.get_all(), headers={'Access-Control-Allow-Origin': 'http://localhost:3000'})

    user_list, conversation_list = (
        await hangups.build_user_conversation_list(client)
    )

    all_users = user_list.get_all()
    userlist = user_list

    return json(all_users, headers={'Access-Control-Allow-Origin': 'http://localhost:3000'})


@sio.event
async def my_event(sid, message):
    await sio.emit('my_response', {'data': message['data']}, room=sid)

@sio.event
async def conv_message(sid, message):
    print('would send message', message)
    # await convList.get(message['id']).send_message(hangups.ChatMessageSegment.from_str(message['message']))


@sio.event
async def my_broadcast_event(sid, message):
    await sio.emit('my_response', {'data': message['data']})


@sio.event
async def join(sid, message):
    sio.enter_room(sid, message['room'])
    await sio.emit('my_response', {'data': 'Entered room: ' + message['room']},
                   room=sid)


@sio.event
async def leave(sid, message):
    sio.leave_room(sid, message['room'])
    await sio.emit('my_response', {'data': 'Left room: ' + message['room']},
                   room=sid)


@sio.event
async def close_room(sid, message):
    await sio.emit('my_response',
                   {'data': 'Room ' + message['room'] + ' is closing.'},
                   room=message['room'])
    await sio.close_room(message['room'])


@sio.event
async def my_room_event(sid, message):
    await sio.emit('my_response', {'data': message['data']},
                   room=message['room'])


@sio.event
async def disconnect_request(sid):
    await sio.disconnect(sid)


@sio.event
async def connect(sid, environ):
    await sio.emit('my_response', {'data': 'Connected', 'count': 0}, room=sid)


@sio.event
def disconnect(sid):
    print('Client disconnected')


app.static('/static', './static')


if __name__ == '__main__':
    app.run()

