import json
from threading import Thread, Event

import requests
from flask import Flask, jsonify, make_response, abort
from flask_cors import CORS
from flask_socketio import SocketIO
from steam import game_servers as gs


app = Flask(__name__)
ws = SocketIO(app, async_mode="eventlet", logger=True, engineio_logger=True, cors_allowed_origins="*")

CORS(app)

thread = Thread()
thread_stop_event = Event()


def update_thread():
    print("Update loop started")
    ws.sleep(5)
    while not thread_stop_event.isSet():
        for cat in get_servers():
            ws.emit('votes_update', {'server': cat, "votes": get_vote_data(cat)["votes"]}, namespace='/wss')
            for server in get_steam_data(cat)[cat]:
                ws.emit('server_update', {'server': server}, namespace='/wss')
                ws.sleep(.1)
        ws.sleep(1)


def get_servers():
    with open('servers.json') as f:
        return json.load(f)


def get_steam_data(game):
    steam_data = {game: []}
    for server in get_servers()[game]:
        try:
            steam_info = gs.a2s_info((server["ip"], server["port"]))
            server_json = {"name": server["name"],
                           "status": "ok",
                           "ping": round(steam_info["_ping"], 2),
                           "ip": f"{server['ip']}:{server['port']}",
                           # "online_players": gs.a2s_players((server["ip"], server["port"])),
                           "players": steam_info["players"],
                           "max_players": steam_info["max_players"],
                           "version": steam_info["version"]}
            steam_data[game].append(server_json)
        except:
            server_json = {"name": server["name"],
                           "status": "Down",
                           "ping": 0,
                           "ip": f"{server['ip']}:{server['port']}",
                           "players": 0,
                           "max_players": 0,
                           "version": 0}
            steam_data[game].append(server_json)
    return steam_data


def get_discord_data():
    discord = requests.get("https://discordapp.com/api/guilds/516135382191177728/widget.json")
    if discord.status_code == 429:
        discord = {"online": 555, "invite": "https://discord.gg/YFSp8qE"}
    else:
        discord = discord.json()
        online = discord["presence_count"]
        invite = discord["instant_invite"]
        discord = {"online": online, "invite": invite}
    return discord


def get_vote_data(game):
    valid_games = get_servers()
    if game not in valid_games:
        return {"votes": 0, "voters": []}
    ark = ""
    se = ""
    sdtd = ""
    link = ""
    if game.lower() == "ark":
        link = ark
    elif game.lower() == "se":
        link = se
    elif game.lower() == "ld2d":
        link = sdtd
    else:
        return {"votes": 0, "voters": []}
    if link == "":
        return {"votes": 0, "voters": []}
    votes = requests.get(link)
    votes = votes.json()
    voters = votes["voters"]
    votes = sum([int(v["votes"]) for v in voters])
    return {"votes": votes, "voters": voters}


@ws.on('connect', namespace='/wss')
def connect():
    global thread
    print('Client connected')
    if not thread.isAlive():
        print("Starting Thread")
        thread = ws.start_background_task(update_thread)


@ws.on('disconnect', namespace='/wss')
def disconnect():
    print('Client disconnected')


@app.errorhandler(400)
def not_found(error):
    return make_response(jsonify({'error': 'Bad request'}), 400)


@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({'error': 'Not found'}), 404)


@app.route("/servers/<game>")
def server_info(game):
    valid_games = get_servers()
    if game not in valid_games:
        abort(404)
    return jsonify({"servers": get_steam_data(game)[game]})


@app.route("/players/<ip>")
def players(ip):
    ip = ip.split(':')
    try:
        player_data = gs.a2s_players((ip[0], int(ip[1])))
        return jsonify({"players": player_data})
    except:
        abort(404)


@app.route("/votes/<game>")
def vote_info(game):
    valid_games = get_servers()
    if game not in valid_games:
        abort(404)
    return jsonify(get_vote_data(game))


if __name__ == '__main__':
    ws.run(app, port=8000)
