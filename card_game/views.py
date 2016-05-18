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
from .forms import AddPlayer, LoginForm
from engine import *
from .models import Player, Game
from .schema import *


def broadcast():
    time.sleep(3)
    game = set_game()
    card = game.show_card(game.last_card_played)
    socketio.emit('my response',
                {'data': card, 'player': game.last_player.player,
                'turn': game.act_player.player },
                namespace='/test', broadcast=True)

def set_game():
    query = Game.query.first()

    if query:
        g = json.loads(str(query.game))
        game = CardGameSchema().load(g)
        return game.data

    else:
        return 0


def save_game(game):
    dic = CardGameSchema().dump(game)
    d = json.dumps(dic.data)
    query = Game.query.first()

    if query:
        query.game = d
        db.session.add(query)
        db.session.commit()

        thread = Thread(target=broadcast)
        thread.daemon = True
        thread.start()

    else:
        g = Game(game=d)
        db.session.add(g)
        db.session.commit()

        thread = Thread(target=broadcast)
        thread.daemon = True
        thread.start()


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
    game = set_game()

    if game:
        if current_user.is_playing(game):
            game.player_quit(current_user.username)
            save_game(game)

    logout_user()
    session.clear()
    return redirect(url_for('index'))


@app.route('/preparation', methods=['GET', 'POST'])
def preparation():
    player_list = Player.query.all()
    game = set_game()

    if game:
        if current_user.is_playing(game):
            return redirect('playing')

    return render_template('preparation.html', player_list=player_list)


@app.route('/ready', methods=['GET', 'POST'])
def ready():
    player_list = request.form.getlist("add")
    game = CardGame(player_list)
    game.start_game()
    save_game(game)
    return redirect(url_for('playing'))


@app.route('/playing')
def playing():
    game = set_game()

    if not game.winner:
        return render_template('playing.html', game=game)

    else:
        return redirect(url_for('winner'))


@app.route('/play/<card>', methods=['POST', 'GET'])
def play(card):
    game = set_game()

    try:
        game = current_user.play(game, int(card))
        save_game(game)
        return redirect(url_for('playing'))

    except ValueError as error:
        flash(str(error))
        return redirect('/playing')


@app.route('/draw')
def draw():
    game = set_game()
    try:
        game = current_user.draw(game)
        save_game(game)
        return redirect(url_for('playing'))
    except ValueError as error:
        flash(str(error))
        return redirect('/playing')


@app.route('/winner')
def winner():
    query = Game.query.first()
    u = Player.query.filter_by(username=game.winner).first()
    u.score += 2
    db.session.add(u)
    db.session.delete(query)
    db.session.commit()
    return render_template('winner.html', game=game)