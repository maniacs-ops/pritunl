from pritunl.constants import *
from pritunl.exceptions import *
from pritunl import utils
from pritunl import static
from pritunl import organization
from pritunl import settings
from pritunl import app
from pritunl import auth
from pritunl import mongo
from pritunl import sso
from pritunl import event
from pritunl import logger

import flask
import time
import pymongo
import hmac
import hashlib
import base64
import urlparse

def _get_key_tar_archive(org_id, user_id):
    org = organization.get_by_id(org_id)
    usr = org.get_user(user_id)
    key_archive = usr.build_key_tar_archive()
    response = flask.Response(response=key_archive,
        mimetype='application/octet-stream')
    response.headers.add('Content-Disposition',
        'attachment; filename="%s.tar"' % usr.name)
    return response

def _get_key_zip_archive(org_id, user_id):
    org = organization.get_by_id(org_id)
    usr = org.get_user(user_id)
    key_archive = usr.build_key_zip_archive()
    response = flask.Response(response=key_archive,
        mimetype='application/octet-stream')
    response.headers.add('Content-Disposition',
        'attachment; filename="%s.zip"' % usr.name)
    return response

def _get_onc_archive(org_id, user_id):
    org = organization.get_by_id(org_id)
    user = org.get_user(user_id)
    key_archive = user.build_onc_archive()
    response = flask.Response(response=key_archive,
        mimetype='application/octet-stream')
    response.headers.add('Content-Disposition',
        'attachment; filename="%s.zip"' % user.name)
    return response

def _find_doc(query, one_time=None):
    utils.rand_sleep()

    collection = mongo.get_collection('users_key_link')
    doc = collection.find_one(query)

    if one_time and doc and doc.get('one_time'):
        collection = mongo.get_collection('users_key_link')
        response = collection.update({
            '_id': doc['_id'],
            'short_id': doc['short_id'],
            'one_time': True,
        }, {'$set': {
            'one_time': 'used',
        }})
        if not response['updatedExisting']:
            raise KeyError('Key link does not exists')

    if not doc:
        time.sleep(settings.app.rate_limit_sleep)

    return doc

@app.app.route('/key/<org_id>/<user_id>.tar', methods=['GET'])
@auth.session_auth
def user_key_tar_archive_get(org_id, user_id):
    return _get_key_tar_archive(org_id, user_id)

@app.app.route('/key/<org_id>/<user_id>.zip', methods=['GET'])
@auth.session_auth
def user_key_zip_archive_get(org_id, user_id):
    return _get_key_zip_archive(org_id, user_id)

@app.app.route('/key_onc/<org_id>/<user_id>.zip', methods=['GET'])
@auth.session_auth
def user_key_onc_archive_get(org_id, user_id):
    return _get_onc_archive(org_id, user_id)

@app.app.route('/key/<org_id>/<user_id>', methods=['GET'])
@auth.session_auth
def user_key_link_get(org_id, user_id):
    org = organization.get_by_id(org_id)
    return utils.jsonify(org.create_user_key_link(user_id))

@app.app.route('/key/<key_id>.tar', methods=['GET'])
def user_linked_key_tar_archive_get(key_id):
    doc = _find_doc({
        'key_id': key_id,
    })
    if not doc:
        return flask.abort(404)

    return _get_key_tar_archive(doc['org_id'], doc['user_id'])

@app.app.route('/key/<key_id>.zip', methods=['GET'])
def user_linked_key_zip_archive_get(key_id):
    doc = _find_doc({
        'key_id': key_id,
    })
    if not doc:
        return flask.abort(404)

    return _get_key_zip_archive(doc['org_id'], doc['user_id'])

@app.app.route('/key_onc/<key_id>.zip', methods=['GET'])
def user_linked_key_onc_archive_get(key_id):
    doc = _find_doc({
        'key_id': key_id,
    })
    if not doc:
        return flask.abort(404)

    return _get_onc_archive(doc['org_id'], doc['user_id'])

@app.app.route('/k/<short_code>', methods=['GET'])
def user_linked_key_page_get(short_code):
    doc = _find_doc({
        'short_id': short_code,
    }, one_time=True)
    if not doc:
        return flask.abort(404)

    org = organization.get_by_id(doc['org_id'])
    user = org.get_user(id=doc['user_id'])

    if settings.local.sub_active and settings.app.theme == 'dark':
        view_name = KEY_VIEW_DARK_NAME
    else:
        view_name = KEY_VIEW_NAME

    key_page = static.StaticFile(settings.conf.www_path, view_name,
        cache=False).data
    key_page = key_page.replace('<%= user_name %>', '%s - %s' % (
        org.name, user.name))
    key_page = key_page.replace('<%= user_key_tar_url %>', '/key/%s.tar' % (
        doc['key_id']))
    key_page = key_page.replace('<%= user_key_zip_url %>', '/key/%s.zip' % (
        doc['key_id']))

    if org.otp_auth:
        key_page = key_page.replace('<%= user_otp_key %>', user.otp_secret)
        key_page = key_page.replace('<%= user_otp_url %>',
            'otpauth://totp/%s@%s?secret=%s' % (
                user.name, org.name, user.otp_secret))
    else:
        key_page = key_page.replace('<%= user_otp_key %>', '')
        key_page = key_page.replace('<%= user_otp_url %>', '')

    key_page = key_page.replace('<%= short_id %>', doc['short_id'])

    conf_links = ''

    if settings.local.sub_active:
        conf_links += '<a class="btn btn-success" ' + \
            'title="Download Chromebook Profiles" ' + \
            'href="/key_onc/%s.zip">Download Chromebook Profiles</a><br>\n' % (
                doc['key_id'])

    for server in org.iter_servers():
        conf_links += '<a class="btn btn-sm" title="Download Profile" ' + \
            'href="/key/%s/%s.key">Download Profile (%s)</a><br>\n' % (
                doc['key_id'], server.id, server.name)
    key_page = key_page.replace('<%= conf_links %>', conf_links)

    return key_page

@app.app.route('/k/<short_code>', methods=['DELETE'])
def user_linked_key_page_delete_get(short_code):
    utils.rand_sleep()

    collection = mongo.get_collection('users_key_link')
    collection.remove({
        'short_id': short_code,
    })

    return utils.jsonify({})

@app.app.route('/ku/<short_code>', methods=['GET'])
def user_uri_key_page_get(short_code):
    doc = _find_doc({
        'short_id': short_code,
    }, one_time=True)

    if not doc:
        return flask.abort(404)

    org = organization.get_by_id(doc['org_id'])
    user = org.get_user(id=doc['user_id'])

    keys = {}
    for server in org.iter_servers():
        key = user.build_key_conf(server.id)
        keys[key['name']] = key['conf']

    return utils.jsonify(keys)

@app.app.route('/key/<key_id>/<server_id>.key', methods=['GET'])
def user_linked_key_conf_get(key_id, server_id):
    doc = _find_doc({
        'key_id': key_id,
    })
    if not doc:
        return flask.abort(404)

    org = organization.get_by_id(doc['org_id'])
    user = org.get_user(id=doc['user_id'])
    key_conf = user.build_key_conf(server_id)

    response = flask.Response(response=key_conf['conf'],
        mimetype='application/octet-stream')
    response.headers.add('Content-Disposition',
        'attachment; filename="%s"' % key_conf['name'])

    return response

@app.app.route('/key/<org_id>/<user_id>/<server_id>/<key_hash>',
    methods=['GET'])
def key_sync_get(org_id, user_id, server_id, key_hash):
    utils.rand_sleep()

    if not settings.local.sub_active:
        return utils.response('', status_code=480)

    auth_token = flask.request.headers.get('Auth-Token', None)
    auth_timestamp = flask.request.headers.get('Auth-Timestamp', None)
    auth_nonce = flask.request.headers.get('Auth-Nonce', None)
    auth_signature = flask.request.headers.get('Auth-Signature', None)
    if not auth_token or not auth_timestamp or not auth_nonce or \
            not auth_signature:
        return flask.abort(401)
    auth_nonce = auth_nonce[:32]

    try:
        if abs(int(auth_timestamp) - int(utils.time_now())) > \
                settings.app.auth_time_window:
            return flask.abort(401)
    except ValueError:
        return flask.abort(401)

    org = organization.get_by_id(org_id)
    if not org:
        return flask.abort(401)

    user = org.get_user(id=user_id)
    if not user:
        return flask.abort(401)
    elif not user.sync_secret:
        return flask.abort(401)

    auth_string = '&'.join([
        auth_token, auth_timestamp, auth_nonce, flask.request.method,
        flask.request.path] +
        ([flask.request.data] if flask.request.data else []))

    if len(auth_string) > AUTH_SIG_STRING_MAX_LEN:
        return flask.abort(401)

    auth_test_signature = base64.b64encode(hmac.new(
        user.sync_secret.encode(), auth_string,
        hashlib.sha512).digest())
    if auth_signature != auth_test_signature:
        return flask.abort(401)

    nonces_collection = mongo.get_collection('auth_nonces')
    try:
        nonces_collection.insert({
            'token': auth_token,
            'nonce': auth_nonce,
            'timestamp': utils.now(),
        }, w=0)
    except pymongo.errors.DuplicateKeyError:
        return flask.abort(401)

    key_conf = user.sync_conf(server_id, key_hash)
    if key_conf:
        return utils.response(key_conf['conf'])
    return utils.response('')

@app.app.route('/sso/authenticate', methods=['POST'])
def sso_authenticate_post():
    if settings.app.sso != DUO_AUTH:
        return flask.abort(405)

    username = flask.request.json['username']
    usernames = [username]
    email = None
    if '@' in username:
        email = username
        usernames.append(username.split('@')[0])

    valid = False
    for username in usernames:
        try:
            valid, org_id = sso.auth_duo(
                username,
                strong=True,
                ipaddr=flask.request.remote_addr,
                type='Key',
            )
            break
        except InvalidUser:
            pass

    if not valid:
        return flask.abort(401)

    if not org_id:
        org_id = settings.app.sso_org

    org = organization.get_by_id(org_id)
    if not org:
        return flask.abort(405)

    usr = org.find_user(name=username)
    if not usr:
        usr = org.new_user(name=username, email=email, type=CERT_CLIENT,
            auth_type=DUO_AUTH)
        event.Event(type=ORGS_UPDATED)
        event.Event(type=USERS_UPDATED, resource_id=org.id)
        event.Event(type=SERVERS_UPDATED)
    elif usr.auth_type != DUO_AUTH:
        usr.auth_type = DUO_AUTH
        usr.commit('auth_type')

    key_link = org.create_user_key_link(usr.id, one_time=True)

    return flask.request.url_root[:-1] + key_link['view_url']

@app.app.route('/sso/request', methods=['GET'])
def sso_request_get():
    if settings.app.sso not in (GOOGLE_AUTH, GOOGLE_DUO_AUTH,
            SAML_AUTH, SAML_DUO_AUTH):
        return flask.abort(405)

    state = utils.rand_str(64)
    secret = utils.rand_str(64)
    callback = flask.request.url_root + 'sso/callback'

    if not settings.local.sub_active:
        return flask.abort(405)

    if settings.app.sso in (GOOGLE_AUTH, GOOGLE_DUO_AUTH):
        resp = utils.request.post(AUTH_SERVER + '/v1/request/google',
            json_data={
                'license': settings.app.license,
                'callback': callback,
                'state': state,
                'secret': secret,
            }, headers={
                'Content-Type': 'application/json',
            })

        if resp.status_code != 200:
            if resp.status_code == 401:
                return flask.abort(405)

            logger.error('Auth server error', 'server',
                status_code=resp.status_code,
                content=resp.content,
            )

            return flask.abort(500)

        tokens_collection = mongo.get_collection('sso_tokens')
        tokens_collection.insert({
            '_id': state,
            'type': GOOGLE_AUTH,
            'secret': secret,
            'timestamp': utils.now(),
        })

        data = resp.json()

        return flask.redirect(data['url'])

    elif settings.app.sso in (SAML_AUTH, SAML_DUO_AUTH):
        resp = utils.request.post(AUTH_SERVER + '/v1/request/saml',
            json_data={
                'license': settings.app.license,
                'callback': callback,
                'state': state,
                'secret': secret,
                'sso_url': settings.app.sso_saml_url,
                'issuer_url': settings.app.sso_saml_issuer_url,
                'cert': settings.app.sso_saml_cert,
            }, headers={
                'Content-Type': 'application/json',
            })

        if resp.status_code != 200:
            if resp.status_code == 401:
                return flask.abort(405)

            logger.error('Auth server error', 'server',
                status_code=resp.status_code,
                content=resp.content,
            )

            return flask.abort(500)

        tokens_collection = mongo.get_collection('sso_tokens')
        tokens_collection.insert({
            '_id': state,
            'type': SAML_AUTH,
            'secret': secret,
            'timestamp': utils.now(),
        })

        return flask.Response(
            status=200,
            response=resp.content,
            content_type="text/html;charset=utf-8",
        )

@app.app.route('/sso/callback', methods=['GET'])
def sso_callback_get():
    sso_mode = settings.app.sso

    if sso_mode not in (GOOGLE_AUTH, GOOGLE_DUO_AUTH,
            SAML_AUTH, SAML_DUO_AUTH):
        return flask.abort(405)

    state = flask.request.args.get('state')
    sig = flask.request.args.get('sig')

    tokens_collection = mongo.get_collection('sso_tokens')
    doc = tokens_collection.find_and_modify(query={
        '_id': state,
    }, remove=True)

    if not doc:
        return flask.abort(404)

    query = flask.request.query_string.split('&sig=')[0]
    test_sig = base64.urlsafe_b64encode(hmac.new(str(doc['secret']),
        query, hashlib.sha512).digest())

    if sig != test_sig:
        return flask.abort(401)

    params = urlparse.parse_qs(query)

    if doc.get('type') == SAML_AUTH:
        username = params.get('username')[0]
        email = params.get('email', [None])[0]
        org_name = params.get('org', [None])[0]

        if not username:
            return flask.abort(406)

        valid, org_name = sso.verify_saml(username, email, org_name)
        if not valid:
            return flask.abort(401)

        org = organization.get_by_name(org_name, fields=('_id'))
        if org:
            org_id = org.id
        else:
            org_id = settings.app.sso_org

    else:
        username = params.get('username', [None])[0]
        email = username

        valid, org_id = sso.verify_google(username)
        if not valid:
            return flask.abort(401)

        if not org_id:
            org_id = settings.app.sso_org

    auth_type = sso_mode

    if DUO_AUTH in sso_mode and DUO_AUTH in auth_type:
        valid, _ = sso.auth_duo(
            username,
            ipaddr=flask.request.remote_addr,
            type='Key',
        )
        if not valid:
            return flask.abort(401)

    org = organization.get_by_id(org_id)
    if not org:
        return flask.abort(405)

    usr = org.find_user(name=username)
    if not usr:
        usr = org.new_user(name=username, email=email, type=CERT_CLIENT,
            auth_type=auth_type)
        event.Event(type=ORGS_UPDATED)
        event.Event(type=USERS_UPDATED, resource_id=org.id)
        event.Event(type=SERVERS_UPDATED)
    elif usr.auth_type != auth_type:
        usr.auth_type = auth_type
        usr.commit('auth_type')

    key_link = org.create_user_key_link(usr.id, one_time=True)

    return flask.redirect(flask.request.url_root[:-1] + key_link['view_url'])
