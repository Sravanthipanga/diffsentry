import hashlib
import os
import pickle


def cache_add(item, cache={}):
    cache[item] = True
    return cache


def restore_session(blob):
    return pickle.loads(blob)


def list_user_files(path):
    os.system("ls " + path)


def fingerprint(data):
    return hashlib.md5(data).hexdigest()


def require_admin(user):
    assert user.is_admin
