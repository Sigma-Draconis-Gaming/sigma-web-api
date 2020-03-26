import json
from threading import Thread, Event

import mysql.connector
import requests
from flask import Flask, jsonify, make_response, abort
from flask_cors import CORS
from flask_mysqldb import MySQL
from flask_socketio import SocketIO
from steam import game_servers as gs

servers = {"SEDS1": "Sigma", "SEDS2": "Tau", "SEDS3": "Omicron", "SEDS4": "Gamma", "SEDS5": "Delta", "SEDS6": "Epsilon"}

app = Flask(__name__)
app.config.from_object("config.ProductionConfig")
ws = SocketIO(app, async_mode="eventlet", logger=True, engineio_logger=True, cors_allowed_origins="*")
db = mysql.connector.connect(
    host=app.config['MYSQL_HOST'],
    user=app.config['MYSQL_USER'],
    passwd=app.config['MYSQL_PASSWORD']
)


def fix_name(Score_Dict):
    for x in servers.keys():
        if Score_Dict["Server"] == x:
            Score_Dict["Server"] = servers[x]
    Score_Dict['PlanetId'] = Score_Dict["PlanetId"].split("-")[0]
    print(Score_Dict)
    return Score_Dict


CORS(app)
mysql = MySQL(app)

thread = Thread()
thread_stop_event = Event()


def update_thread():
    print("Update loop started")
    ws.sleep(5)
    while not thread_stop_event.isSet():
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT * FROM sj.kothscores")
        data = cur.fetchall()
        data = map(fix_name, data)
        cur.close()
        ws.emit('scores_update', {"scores": list(data)}, namespace='/wss')
        for cat in get_servers():
            ws.emit('votes_update', {'server': cat, "votes": get_vote_data(cat)["votes"]}, namespace='/wss')
            s = get_steam_data(cat)[cat]
            t = sum([int(x['players']) for x in s])
            ws.emit("online_update", {'id_key': f'{cat}_count', 'count': t}, namespace='/wss')
            for server in s:
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
    ark = app.config["ARK_VOTE_LINK"]
    se = app.config["SE_VOTE_LINK"]
    if game.lower() == "ark":
        link = ark
    elif game.lower() == "se":
        link = se
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


@app.route("/online/<game>")
def online_info(game):
    valid_games = get_servers()
    if game not in valid_games:
        abort(404)
    s = get_steam_data(game)[game]
    t = sum([int(x['players']) for x in s])
    return jsonify({"players": t})


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


@app.route("/scores")
@app.route("/scores/<server>")
@app.route("/scores/<server>/<planet>")
def scores(server=None, planet=None):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM sj.kothscores")
    data = cur.fetchall()
    data = map(fix_name, data)
    cur.close()
    if server:
        s_data = list([x for x in list(data) if x['Server'].lower() == server.lower()])
        if len(s_data) > 0:
            if planet:
                s = [x for x in s_data if x['PlanetId'].lower() == planet.lower()]
                print("?")
                print(s)
                if len(s) < 1:
                    return jsonify({"msg": "not found"}), 404
                return jsonify({"scores": s})
            return jsonify({"scores": list(s_data)})
        else:
            return jsonify({"msg": "not found"}, 404)
    return jsonify({"scores": list(data)})


if __name__ == '__main__':
    ws.run(app, host="0.0.0.0", port=8000)
