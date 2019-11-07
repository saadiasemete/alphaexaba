from flask import Flask, request, jsonify
from flask.views import View
from new_post import submit_post
from view_post import open_post
from new_board import submit_board
from sqlalchemy import create_engine
from database import meta
import time

from sqlalchemy.orm import sessionmaker

app = Flask(__name__)

#engine = create_engine('sqlite:///:memory:', echo=True)
engine = create_engine('sqlite:///here.db', echo=True)
SA_Session = sessionmaker(bind=engine)

def append_to_data(data):
    app.config.from_json("cfg.json")
    data['__headers__'] = request.headers
    data['__config__'] = app.config
    data['__files__'] = request.files
    return data

def get_data_mimetype_agnostic():
    """
    I'm still figuring this out and not sure
    if I don't need to send anything else
    depending on the mimetype.
    """
    if request.is_json:
        return (append_to_data(request.json),)
    elif request.form:
        return (append_to_data(request.form.to_dict()),)
    elif request.method == 'GET':
        return request.view_args if request.view_args else {}


def json_from_sqlalchemy_row(row):
    row.id #let sqlalchemy refresh the object
    return {i.name: row.__dict__.get(i.name) for i in row.__table__.columns}


class StandardRequest(View):
    data_fetcher = get_data_mimetype_agnostic
    target_status = 200
    query_processing = NotImplemented
    answer_processing = json_from_sqlalchemy_row
    def dispatch_request(self):
        data = self.__class__.data_fetcher()
        answer = self.__class__.query_processing(data[0], SA_Session())
        if answer[0]==201: #HTTP 201: CREATED
            response = {
                    'result': True,
                    'data': self.__class__.answer_processing(answer[1]),
                }
        else:
            response = {
                    'result': False,
                    'data': answer[1],
                }
        return jsonify(response), answer[0]

class NewBoard(StandardRequest):
    target_status = 201
    query_processing = submit_board

class NewPost(StandardRequest):
    target_status = 201
    query_processing = submit_post

class ViewPost(StandardRequest):
    target_status = 200
    query_processing = open_post

app.add_url_rule('/api/new_board', view_func = NewBoard.as_view('new_board'), methods = ['POST'])
app.add_url_rule('/api/new_post', view_func = NewPost.as_view('new_post'), methods = ['POST'])

#DELETE AFTER DEBUG
meta.drop_all(engine)
meta.create_all(engine)
app.run(debug = True)