from ..database import Board, Ban, Post, Captcha
import time
from sqlalchemy import and_
from . import post_checks, query_processor
from ..current_timestamp import current_timestamp

class SubmitBoard(query_processor.QueryProcessor):
    checkers = [
        {
            "checker": post_checks.is_invalid_data,
        },
        {
            "checker": post_checks.is_board_address_existent,
        },
    ]

    @classmethod
    def apply_transformations(cls, data, db_session):
        """
        In case the post needs to be changed before getting to the db.
        """
        return data

    @classmethod
    def on_checks_passed(cls, data, db_session):
        """
        Assumes that the post is legit to be posted.
        """
        data = cls.apply_transformations(data, db_session)
        new_board = Board(
            name = data['__data__']['name'],
            address = data['__data__']['address'],
            description = data['__data__'].get('description'),
            created_at = data['__data__']['timestamp'],
            hidden = data['__data__'].get('hidden'),
            admin_only = data['__data__'].get('admin_only'),
            read_only = data['__data__'].get('read_only'),
        )
        db_session.add(new_board)
        db_session.commit()
        return (201, new_board)