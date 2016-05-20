from __future__ import print_function
import sys
import json
from threading import Thread, Lock
import time

from flask import (render_template, redirect, url_for, 
    request, g, flash, session)
from flask.ext.login import (login_user, logout_user, current_user,
    login_required)
from werkzeug.security import generate_password_hash, \
     check_password_hash
from flask.ext.socketio import emit

from . import engine, app, db, socketio
from .forms import AddPlayer, LoginForm, CreateRoom
from engine import *
from .models import Player, Game
from .schema import *


def broadcast_turn(game_name):
    time.sleep(3)
    game = set_game(game_name)
    if game[1].last_card_played and game[1].last_player and game[1].act_player:
        card = game[1].show_card(game[1].last_card_played)
        last_player = game[1].last_player.player
        act_player = game[1].act_player.player
    else:
        card = None
        last_player = None
        act_player = None

    socketio.emit('my response',
                {'data': card, 'player': last_player,
                'turn': act_player },
                namespace='/test', broadcast=True)

def broadcast_join(player):
    time.sleep(2)
    socketio.emit('join',
        {'data': player}, namespace='/test',
        broadcast=True)

def broadcast_start():
    time.sleep(2)
    socketio.emit('start',
        {'data': None},
        namespace='/test', broadcast=True)

def broadcast_leave(player):
    time.sleep(2)
    socketio.emit('leave',
        {'data': player}, namespace='/test',
        broadcast=True)

def set_game(game_name=None, game_id=None):
    if game_name:
        query = Game.query.filter_by(game_name=game_name).first()
    elif game_id:
        query = Game.query.filter_by(id=game_id).first()

    if query:
        game = []
        game.append(query.game_name)
        g = json.loads(str(query.game))
        game_schema = CardGameSchema().load(g)
        game.append(game_schema.data)
        print(game_schema.data, file=sys.stderr)
        print(game, file=sys.stderr)
        return game

    else:
        return 0

def save_game(game):
    dic = CardGameSchema().dump(game[1])
    d = json.dumps(dic.data)
    query = Game.query.filter_by(game_name=game[0]).first()

    if query:
        query.game_name = game[0]
        query.game = d
        db.session.add(query)
        db.session.commit()

        thread = Thread(target=broadcast_turn(game_name=game[0]))
        thread.daemon = True
        thread.start()

    else:
        g = Game(game_name=game[0], game=d)
        db.session.add(g)
        db.session.commit()

def player_join(game_name):
    u = current_user
    game = Game.query.filter_by(game_name=game_name).first()
    u.game_id = game.id
    db.session.add(u)
    db.session.commit()


@app.route('/')
@app.route('/index')
def index():
    return render_template('index.html')


@app.route('/signup', methods=['GET', 'POST'])
def regist():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = AddPlayer()

    if form.validate_on_submit():
        u = Player(username=form.username.data, 
            password=generate_password_hash(form.password.data),
            score=0)
        db.session.add(u)
        db.session.commit()
        return redirect(url_for('login'))

    return render_template('addplayer.html', form=form, title='Sign Up')


@app.route('/signin', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()

    if form.validate_on_submit():
        u = Player.query.filter_by(username=form.username.data).first()
        
        if not u:
            return redirect(url_for('login'))

        elif check_password_hash(u.password, form.password.data):
            login_user(u)
            return redirect(url_for('index'))

    return render_template('login.html', form=form, title='Sign In')


@app.route('/logout')
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('index'))


@app.route('/preparation', methods=['GET', 'POST'])
def preparation():
    game_list = Game.query.all()

    if current_user.is_playing():
        return redirect('playing')

    return render_template('preparation.html', game_list=game_list)


@app.route('/create_room', methods=['GET', 'POST'])
def create_room():
    form = CreateRoom()
    if form.validate_on_submit():
        game_name = form.game_name.data
        game_object = CardGame()
        game = [game_name, game_object]
        save_game(game)
        return redirect(url_for('game_room', game_name=game_name))
    return render_template('create_room.html', form=form)


@app.route('/game_room/<game_name>', methods=['GET', 'POST'])
def game_room(game_name):
    game = set_game(game_name=game_name)
    if game[1].turn:
        return redirect('playing')
    game[1].add_player(current_user.username)
    save_game(game)
    player_join(game[0])
    thread = Thread(target=broadcast_join(current_user.username))
    thread.daemon = True
    thread.start()
    return render_template('game_room.html', game=game)


@app.route('/ready/<game_name>', methods=['GET', 'POST'])
def ready(game_name):
    game = set_game(game_name=game_name)
    game[1].start_game()
    save_game(game)
    thread = Thread(target=broadcast_start)
    thread.daemon = True
    thread.start()
    return redirect(url_for('playing'))


@app.route('/playing')
def playing():
    game = set_game(game_id=current_user.game_id)

    if not game[1].winner:
        return render_template('playing.html', game=game[1])

    else:
        return redirect(url_for('winner'))


@app.route('/play/<card>', methods=['POST', 'GET'])
def play(card):
    game = set_game(game_id=current_user.game_id)

    try:
        game[1] = current_user.play(game[1], int(card))
        save_game(game)
        return redirect(url_for('playing'))

    except ValueError as error:
        flash(str(error))
        return redirect('/playing')


@app.route('/draw')
def draw():
    game = set_game(game_id=current_user.game_id)

    try:
        game[1] = current_user.draw(game[1])
        save_game(game)
        return redirect(url_for('playing'))
    except ValueError as error:
        flash(str(error))
        return redirect('/playing')


@app.route('/winner')
def winner():
    game = set_game(game_id=current_user.game_id)
    u = Player.query.filter_by(username=game[1].winner).first()
    u.score += 2
    db.session.add(u)
    db.session.commit()
    thread = Thread(target=broadcast_start)
    thread.daemon = True
    thread.start()
    return render_template('winner.html', game=game[1])


@app.route('/player_quit')
def player_quit():
    u = current_user
    game = set_game(game_id=u.game_id)
    u.game_id = None
    game[1].player_quit(u.username)
    db.session.add(u)
    db.session.commit()
    thread = Thread(target=broadcast_leave(u.username))
    thread.daemon = True
    thread.start()
    return redirect(url_for('index'))

#player_list = request.form.getlist("add")
#With selected:
#<input type="submit" value="Add" />