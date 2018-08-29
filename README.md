# appdata-store

Implements a google cloud function that helps to store user and application
information in Google Cloud Datastore.  The interface exposes simple
keyvalue retrieve, post, and delete actions (details below).

## Installation

To launch the appdata cloud function, a Google cloud account is required.
Navigate to the cloud functions section and do the following:

* Create a new cloud HTTP function that uses 2GB of memory
* Select Python3 as the language
* Copy appdata.py into the code snippet box
* Copy requirements.txt into the requirements.txt tab
* Write "appdata" as the function to execute
* Set two environment variables.  Set "JWT_SECRET" to the token secret password.
Set GROUPNAME to the name of the application group that this cloud function is 
supporting.

Creating a function will provide an http link that is the base URL for the endpoints
described below.

## Authentication

The appdata cloud functions do not support Google oauth.
Authentication and authorization is done using JSON
Web Tokens (JWT).  To create a JWT, install the python
JWT tool:

    % pip install PyJWT

To create a token:

    % pyjwt --key=MYSECRET encode email=EMAILADDR level=admin|readwrite|readonly

This will generate an ID which should be passed in the Authorization request header for each call.

Only admins can write to the /data and /users endpoints.


## Usage

Each given application that has a set of authorized user should have a separate cloud
function instance.  The http api has "readonly", "readwrite", and "admin" access
levels.  The interface can be used to save user group information, application information,
and per-user preferences.  API described below:

Access Users Group (admin only)
* GET /users: retrieve a JSON object where each key is a unique user email address
* POST /users: add user(s) to user group (requires JSON input of {"EMAILADDR" : VALUE}
* DELETE /users: remove user(s) specificed by JSON input of ["EMAILADDR"]

Access Application Data
* GET /data/:key (>=readonly): retrieve application data stored at key
* POST/PUT /data/:key (admin): write application data at key with supplied JSON
(POST will do a transactional append, PUT will overwrite with supplied data)
* DELETE /data/:key (admin): remove data from supplied key 

Access User Data
* GET /user/:key (>=readonly): retrieve data for authenticated user at the specified key
* POST/PUT /user/:key (>=readwrite): write user data at key with supplied JSON
(POST will do a transacational append, PUT will overwrite with supplied data)
* DELETE /data/:key (>=readwrite): remove data from supplied key

To call these endpoints, data should be posted as JSON and authorization added to the header.  For
example, to add a user "foo@bar" with "readonly" permission, do the following:

    % curl -X POST -H "Content-Type: application/json" -H "Authorization: Bearer <tokenid>" https://<GOOGLEFUNCTION>/users -d '{"foo@bar": "admin"}'

