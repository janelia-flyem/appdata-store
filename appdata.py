# Imports the Google Cloud client library
from google.cloud.datastore import Client, Entity
import jwt
import os
import json
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
                        if type(task[propname]) == list:
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

def handlerUserData(urlarr, token, data, method):
    if len(urlarr) == 0:
        return abort(400)

    # Instantiates a client
    client = Client()
    # The kind for the new entity
    kind = GROUPNAME
    # The name/ID for the new entity
    propname = urlarr[0]
    # The Cloud Datastore key for the new entity
    key = client.key(kind, token["email"])

    if method == "GET":
        if not isAuthorized(token, "readonly"):
            return abort(404)

        return getData(client, key, propname)

    if not isAuthorized(token, "readwrite"):
        return abort(404)

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

    user = tokeninfo["email"]
    level = tokeninfo["level"]

    pathinfo = request.path.strip("/")
    urlparts = pathinfo.split('/')

    if len(urlparts) == 0:
        abort(400)

    # if data is posted it should be in JSON format
    jsondata = request.get_json(force=True, silent=True)

    # GET /user/:key -- return value (need read permission)
    # POST/PUT/DELETE /user/:key JSON value -- post value (need write permission)
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
