from flask import Flask, request, jsonify, current_app, send_from_directory
from flask.views import View
from flask import Blueprint
from .query_processing import(
    SubmitBoard,
    SubmitPost,
    OpenPost,
    PostUpdates,
    FetchBoards,
) 
from .query_processing import Pagination as PaginationQuery
from .query_processing import utils as query_utils
from sqlalchemy import create_engine
from sqlalchemy.sql import sqltypes
from sqlalchemy.orm import collections
import time
import datetime
from sqlalchemy.inspection import inspect

from sqlalchemy.orm import sessionmaker, scoped_session

app_blueprint = Blueprint(
    "pyexaba_backend",
    "backend_blueprint", #wtf is an import name?
)

def read_db_engine(config):
    """
    Might make it more user-friendly later
    """
    return config['DB_ENGINE']



#engine = create_engine('sqlite:///:memory:', echo=True)

#db_session = scoped_session(sessionmaker(bind=engine))

def simplify_imd(imd):
    """
    Werkzeug's IMD is a huge pain.
    """
    target_dict = imd.to_dict(flat = False)
    return {i:(j[0] if len(j) == 1 else j) for i,j in target_dict.items()}

def expand_filelist(files):
    return {str(i): j for i,j in enumerate(files.getlist('files'))}


def append_to_data(data):
    current_app.config.from_json(current_app.config_file) #include in a factory
    data['__headers__'] = request.headers
    data['__config__'] = current_app.config
    data['__files__'] = expand_filelist(request.files)
    print(data['__files__'])
    data['__data__']['ip_address'] = request.remote_addr
    return data

def get_data_mimetype_agnostic():
    """
    I'm still figuring this out and not sure
    if I don't need to send anything else
    depending on the mimetype.
    """
    if request.is_json:
        result = request.json
    elif request.form:
       result = simplify_imd(request.form)
    elif request.method == 'GET':
        result = simplify_imd(request.args) if request.args else {}
    wrapper = {'__data__': result}
    return (append_to_data(wrapper),)

def preprocess_sqlalchemy_values(column, value):
    if isinstance(value, datetime.datetime) and value:
        return value.isoformat()
    elif isinstance(value, collections.InstrumentedList): #meaning it represents one-to-many backref
        if column == "attachments":
            return process_attachments(value)
    return value


def json_from_sqlalchemy_row(row):
    row.id #let sqlalchemy refresh the object
    result = {}
    for i,j in dict(inspect(row).attrs).items():
        result[i] = preprocess_sqlalchemy_values(i, j.value)
    return result

def process_attachments(attachments):

    return [
        query_utils.generate_path_to_attachment(
        i.mediatype,
        i.filename,
        i.extension,
        current_app.config['PATH']['__PREFIX__'],
        current_app.config['PATH'][i.mediatype.upper()],
        False
    )
    for i in attachments
    ]
        

def unfold_post_list(post_list):
    result_prima = {}
    """
    result = {
        "post_id": {
            "post": post_obj
            "tripcode": trip_obj
            "attachments": [att1, att2, ...]
        }
    }
    """
    for i in post_list:
        result_prima.setdefault(
            i.Post.id, {"post": i.Post, 
            #"tripcode": i.Tripcode, 
            "attachments": [],}
            )['attachments'].append(i.Attachment)
    result_secunda = []
    for i, j in result_prima.items():
        result_secunda.append(
            {
                "post": json_from_sqlalchemy_row(j['post']),
                #json_from_sqlalchemy_row(j['Tripcode']),
                "attachments": process_attachments(j['attachments']),
            }
        )
    return result_secunda

def unf_list(input_list):

    return  [
        json_from_sqlalchemy_row(i)
        for i in input_list
    ]

def process_pagination_data(pag_data):
    """
    Implies that pag_data will have the following:
    - num_posts_total
    - num_pages_total
    - posts_per_page
    - posts_current_page // - here go the threads
    """
    pag_data['posts_current_page'] = unf_list(pag_data['posts_current_page'])
    return pag_data

class StandardRequest(View):
    
    data_fetcher = get_data_mimetype_agnostic
    target_status = 200
    query_processor = NotImplemented
    answer_processor = json_from_sqlalchemy_row

    @classmethod
    def preprocess_response(cls, response):
        response_jsonified = jsonify(response)
        response_jsonified.headers.add("Access-Control-Allow-Origin", "*")
        return response_jsonified 
    
    @classmethod
    def _build_cors_prelight_response(cls):
        response = make_response()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "*")
        response.headers.add('Access-Control-Allow-Methods', "*")
        return response 

    def dispatch_request(self):
        
        if request.method == 'OPTIONS':
            return self.__class__._build_cors_prelight_response()
        data = self.__class__.data_fetcher()
        db_session = current_app.session_generator(
            bind = current_app.sql_engine
        )
        answer = self.__class__.query_processor.process(data[0], db_session)
        if answer[0]==self.target_status:
            response = {
                    'result': True,
                    'data': self.__class__.answer_processor(answer[1]),
                    'info': None,
                }
        else:
            response = {
                    'result': False,
                    'data': answer[1],
                    'info': None if len(answer)==2 else answer[2], #for details on errors
                }
        db_session.close()
        return self.__class__.preprocess_response(response), answer[0]

class NewBoard(StandardRequest):
    """
    POST
    {body}
    name : string : required
    address : string : required
    description : string : default None
    hidden : boolean : default False
    admin_only : boolean : default False
    read_only : boolean : default False
    ===
    Creates a new board.
    """
    target_status = 201
    query_processor = SubmitBoard

class NewPost(StandardRequest):
    """
    POST
    {body}
    board_id : int|string : required
    to_thread : int|string : default None
    reply_to : int|string : default None
    title : string : default <BLANK>
    text : string : default <BLANK>
    sage : boolean : default False
    ===
    If to_thread is not specified, creates a thread,
    otherwise creates a post.
    Particular conditions depend on settings.
    """
    target_status = 201
    query_processor = SubmitPost

class ViewPost(StandardRequest):
    """
    GET
    {params}
    post_id : int|string : required
    ===
    Gets the post specified, and nothing else.
    """
    target_status = 200
    query_processor = OpenPost
    answer_processor = unf_list

class Pagination(StandardRequest):
    """
    GET
    {params}
    target_type : string : required
    target : string : conditional
    page : int|string : default 1
    ===
    Result depends on target_type.
    1. thread
    Returns the specified page in the target thread.
    2. board
    Returns the specified page in the target board.
    3. post
    Returns the specified page of replies to the target post.
    4. unistream
    Returns the specifed page of the unistream.
    """
    target_status = 200
    query_processor = PaginationQuery
    answer_processor = process_pagination_data

class GetUpdates(StandardRequest):
    """
    GET
    {params}
    target_type : string : required
    target : string : conditional
    ===
    Result depends on target_type.
    1. thread
    Returns new posts in the target thread.
    2. board
    Returns new threads in the target board.
    3. post
    Returns new replies to the target post.
    4. unistream
    Returns new posts in the unistream.
    """
    target_status = 200
    query_processor = PostUpdates
    answer_processor = unf_list

class ViewPost(StandardRequest):
    """
    GET
    {params}
    post_id : int|string : required
    ===
    Gets the post specified, and nothing else.
    """
    target_status = 200
    query_processor = OpenPost
    answer_processor = unf_list

class ListBoards(StandardRequest):
    """
    GET
    ===
    Gets the list of all boards.
    """
    target_status = 200
    query_processor = FetchBoards
    answer_processor = unf_list

app_blueprint.add_url_rule('/api/new_board', view_func = NewBoard.as_view('new_board'), methods = ['POST'])
app_blueprint.add_url_rule('/api/new_post', view_func = NewPost.as_view('new_post'), methods = ['POST'])
app_blueprint.add_url_rule('/api/view_post', view_func = ViewPost.as_view('view_post'), methods = ['GET'])
app_blueprint.add_url_rule('/api/pagination', view_func = Pagination.as_view('pagination'), methods = ['GET'])
app_blueprint.add_url_rule('/api/get_updates', view_func = GetUpdates.as_view('get_updates'), methods = ['GET'])
app_blueprint.add_url_rule('/api/list_boards', view_func = ListBoards.as_view('list_boards'), methods = ['GET'])

#DELETE AFTER DEBUG

#generate_app()