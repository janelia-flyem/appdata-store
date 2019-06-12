import os
import re
import json
# Imports the Google Cloud client library
from google.cloud.datastore import Client, Entity
import jwt
from flask import abort, make_response
import requests

# Environment variables

# private password for decoding JWT ("email", "level": "read"|"readwrite"|"admin")
# currently JWT should be created outside of this program
SECRET = os.environ["JWT_SECRET"]

GITTOKEN = os.environ["GIT_TOKEN"]

# name of application authorization group -- must be a name of kind
GROUPNAME = os.environ["GROUPNAME"]

def getLevel(levelstr):
    level = -1
    if levelstr == "readonly":
        level = 0
    elif levelstr == "readwrite":
        level = 1
    elif levelstr == "admin":
        level = 2
    return level

def isAuthorized(tokenInfo, levelstr):
    if "level" not in tokenInfo:
        return False
    levelstr2 = tokenInfo["level"]
    level = getLevel(levelstr)
    level2 = getLevel(levelstr2)

    return level2 >= level

def getData(client, key, propname):
    try:
        task = client.get(key)
        if not task or propname not in task:
            return json.dumps({})
        return json.dumps(task[propname])
    except:
        return abort(400)

def setData(client, key, propname, data, method):
    # save data to datastore
    try:
        with client.transaction():
            task = client.get(key)
            if not task:
                task = Entity(key)
                task.update({
                    propname: data
                })
            else:
                # overwrite data for put
                if method == "PUT":
                    task[propname] = data
                # append data for post
                elif method == "POST":
                    if propname in task:
                        if isinstance(task[propname], list):
                            task[propname].append(data)
                        else:
                            task[propname] = [task[propname], data]
                    else:
                        task[propname] = [data]
                elif method == "DELETE":
                    del task[propname]
            client.put(task)
    except:
        return abort(400)
    return ""

def handlerGitInfo(urlarr, data):
    if len(urlarr) > 0:
        return abort(400)

    #parse org info
    org = data["organization"]

    # use saved token
    GITHUB_API = "https://api.github.com/graphql"

    request = {"query" : '{ organization(login: "' + org + '") { repositories(first: 50, orderBy: {field: NAME, direction:ASC}) { edges { node { name issues(first:50, states:[OPEN], labels: [user]) { edges { node { title url number body labels(first: 20) {edges {label: node {name}}}}}}}}}}}'}
    headers = {'Authorization': 'token %s' % GITTOKEN}
    r = requests.post(url=GITHUB_API, json=request, headers=headers)

    if r.status_code != 200:
        return abort(r.status_code)
    jsondata = r.json()
    return json.dumps(jsondata)


def get_rest(client, key):
    """ fetch the value of 'key' from the data store and return it"""
    item = client.get(key)
    if not item:
        return abort(404)
    return json.dumps(item)

def get_rest_query(client, ancestor, propname):
    """ search the data store for decendants of ancestor of kind specified in 'propname'"""
    # create a search query that filters results based on the logged in
    # users email address and the key kind.
    clientquery = client.query(kind=propname, ancestor=ancestor)
    res = clientquery.fetch()
    if res:
        items = [{'id': item.id, 'value': item} for item in res]
        return json.dumps(items)
    return abort(404)

def handleRest(urlarr, token, data, method):
    print('handled by REST')

    # unpack property id and name
    propname, *prop_id = urlarr
    prop_id = int(prop_id[0]) if prop_id else None

    # we don't allow puts or deletes on the whole collection
    if not prop_id and re.match(r"^DELETE|PUT$", method):
        return abort(405)

    # don't allow posts to an individual item
    if prop_id and method == "POST":
        return abort(409)

    # set up the client
    kind = GROUPNAME
    client = Client()

    # create the key
    if prop_id:
        # create a full key
        key = client.key(kind, token["email"], propname, prop_id)
    else:
        # create a partial key
        key = client.key(kind, token["email"], propname)


    # if GET return the data
    if method == "GET":
        if key.is_partial:
            ancestor = client.key(kind, token['email'])
            return get_rest_query(client, ancestor, propname)
        return get_rest(client, key)

    # if POST create new entry or PUT overwrite
    if re.match(r"^POST|PUT$", method):
        entity = Entity(key=key)
        entity.update(data)
        client.put(entity)
        # return 200 OK with entity id in the payload
        return json.dumps({})

    # if DELETE remove entry
    if method == "DELETE":
        client.delete(key)
        return json.dumps({})

    return abort(400)


def handlerUserData(urlarr, token, data, method):
    if len(urlarr) == 0:
        return abort(400)

    # check that the token allows read if it is a get request
    if method == "GET" and not isAuthorized(token, "readonly"):
        return abort(404)
    # check that the token allows readwrite for all other methods
    if not isAuthorized(token, "readwrite"):
        return abort(404)

    # short circuit out these two urls as they don't behave the same way
    # as the defaults.
    if urlarr[0] == "searches" or urlarr[0] == "favorites":
        return handleRest(urlarr, token, data, method)

    # Instantiates a client
    client = Client()
    # The kind for the new entity
    kind = GROUPNAME
    # The name/ID for the new entity
    propname = urlarr[0]
    # The Cloud Datastore key for the new entity
    key = client.key(kind, token["email"])

    if method == "GET":
        return getData(client, key, propname)

    # all other methods are set methods
    return setData(client, key, propname, data, method)

def handlerAppData(urlarr, token, data, method):
    if len(urlarr) == 0:
        return abort(400)

    # Instantiates a client
    client = Client()
    # The kind for the new entity
    kind = GROUPNAME
    # Use a seperate entity for app data stored
    propname = "data"
    # The Cloud Datastore key for the new entity
    key = client.key(kind, urlarr[0])

    if method == "GET":
        if not isAuthorized(token, "readonly"):
            return abort(404)

        return getData(client, key, propname)

    if not isAuthorized(token, "admin"):
        return abort(404)

    return setData(client, key, propname, data, method)


def handlerUsers(token, userdata, method):
    if not isAuthorized(token, "admin"):
        return abort(404)

    # Instantiates a client
    client = Client()
    # The kind for the new entity
    kind = GROUPNAME
    # The Cloud Datastore key for the new entity
    key = client.key(kind, "users")

    if method == "GET":
        try:
            task = client.get(key)
            # no users saved
            if not task:
                return json.dumps({})
            return json.dumps(task)
        except Exception as e:
            return abort(400)
    elif method == "POST" or method == "PUT":
        try:
            with client.transaction():
                task = client.get(key)
                if not task:
                    task = Entity(key)
                task.update(userdata)
                client.put(task)
        except:
            return abort(400)
    elif method == "DELETE":
        try:
            with client.transaction():
                task = client.get(key)
                if not task:
                    return abort(400)
                else:
                    for user in userdata:
                        del task[user]
                client.put(task)
        except Exception as e:
            print(e)
            return abort(400)
    else:
        return abort(400)

    return ""

def appdata(request):
    """Responds to any HTTP request.
    Args:
        request (flask.Request): HTTP request object.
    Returns:
        The response text or any set of values that can be turned into a
        Response object using
        `make_response <http://flask.pocoo.org/docs/0.12/api/#flask.Flask.make_response>`.
    """
    # handle preflight request
    if request.method == "OPTIONS":
        resp = make_response("")
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, GET, DELETE, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        return resp
    # extract jwt token
    auth = request.headers.get('authorization')
    if auth is None or auth == "":
        return abort(401)
    authlist = auth.split(' ')
    if len(authlist) != 2:
        return abort(401) # Bearer must be specified
    auth = authlist[1]

    tokeninfo = None
    try:
        tokeninfo = jwt.decode(str.encode(auth), SECRET, algorithms=['HS256'])
    except:
        return abort(401) # error in decoding JWT

    pathinfo = request.path.strip("/")
    urlparts = pathinfo.split('/')

    if len(urlparts) == 0:
        abort(400)

    # if data is posted it should be in JSON format
    jsondata = request.get_json(force=True, silent=True)

    # GET /user/:key -- return value (need read permission)
    # PUT/DELETE /user/:key JSON value -- put value (need write permission)
    # POST /user JSON value -- post value (need write permission)
    if urlparts[0] == "user":
        resp = handlerUserData(urlparts[1:], tokeninfo, jsondata, request.method)
    # GET /users -- return all users and auth (admin)
    # POST /users -- add user and auth
    elif urlparts[0] == "users":
        resp = handlerUsers(tokeninfo, jsondata, request.method)
    # GET /data/:key -- user read permission
    # POST/PUT/DELETE /data/:key -- admin
    elif urlparts[0] == "data":
        resp = handlerAppData(urlparts[1:], tokeninfo, jsondata, request.method)
    elif urlparts[0] == "gitinfo":
        resp = handlerGitInfo(urlparts[1:], jsondata)
    else:
        abort(400)

    resp = make_response(resp)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
    resp.headers['Access-Control-Allow-Methods'] = 'POST, GET, DELETE, OPTIONS'
    return resp
