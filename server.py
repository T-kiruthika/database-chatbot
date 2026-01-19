import os
import re
import json
from flask import Flask, render_template, request, jsonify, session
from flask_session import Session
from langchain_community.utilities import SQLDatabase
import cohere
from urllib.parse import quote_plus
from langchain.memory import ConversationBufferWindowMemory
from sqlalchemy import create_engine, text
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

server_app = Flask(__name__)
server_app.config["SECRET_KEY"] = os.urandom(24)
server_app.config["SESSION_TYPE"] = "filesystem"
server_app.config["SESSION_PERMANENT"] = False
Session(server_app)

try:
    COHERE_API_KEY = os.getenv("COHERE_API_KEY")
    if not COHERE_API_KEY:
        raise ValueError("COHERE_API_KEY not found in environment variables.")
    
    co = cohere.Client(COHERE_API_KEY)
    LLM_CONFIGURED = True
    print("[SUCCESS] Successfully connected to Cohere API.")
except Exception as e:
    print(f"[ERROR] Error configuring Cohere API: {e}.")
    co = None
    LLM_CONFIGURED = False

def get_llm_response(prompt_text):
    if not LLM_CONFIGURED:
        raise Exception("Cohere client is not initialized.")
    response = co.chat(message=prompt_text, temperature=0.1)
    return response.text

session_memory = {}

def extract_sql(text_block):
    """Extracts SQL from markdown blocks or raw strings."""
    match = re.search(r"```sql\n(.*?)\n```", text_block, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text_block.replace("`", "").replace("sql", "").strip()

def generate_html_output(data):
    if not data: return ""
    headers = data[0].keys()
    pretty_headers = [h.replace('_', ' ').title() for h in headers]
    thead = "<thead><tr>" + "".join(f"<th>{h}</th>" for h in pretty_headers) + "</tr></thead>"
    rows = []
    for row_data in data:
        row_values = [str(v) if v is not None else "" for v in row_data.values()]
        rows.append("<tr>" + "".join(f"<td>{v}</td>" for v in row_values) + "</tr>")
    tbody = "<tbody>" + "".join(rows) + "</tbody>"
    return f"<div class='table-container'><table>{thead}{tbody}</table></div>"

def generate_comparative_answer(data):
    if not data or len(data) != 1 or len(data[0]) != 2: return None
    first_row = data[0]
    keys, values = list(first_row.keys()), list(first_row.values())
    if not all(isinstance(v, (int, float, Decimal)) for v in values): return None
    try:
        val1, val2 = float(values[0]), float(values[1])
        metric = keys[0].split('for')[0].replace('_', ' ')
        e1, e2 = keys[0].split('for')[-1].upper(), keys[1].split('for')[-1].upper()
        if val1 > val2: txt = f"Yes, the {metric} for {e1} is higher than for {e2}."
        elif val2 > val1: txt = f"No, the {metric} for {e1} is not higher than for {e2}."
        else: txt = f"The {metric} is the same for both {e1} and {e2}."
        return f"<p>{txt}</p>{generate_html_output(data)}"
    except: return None

def get_sql_query_from_llm(user_question, db, chat_history, last_query, last_query_context=None, error_msg=None, failing_sql=None):
    db_schema = db.get_table_info()
    
    if error_msg:
        prompt = f"""
        ERROR REFLECTION: The previous SQL query failed.
        DATABASE TYPE: {db.dialect}
        FAILING SQL: {failing_sql}
        ERROR FROM DATABASE: {error_msg}
        
        TASK: Analyze the error and generate a fixed, valid SQL query for the question: "{user_question}".
        Ensure table names and column names match the schema exactly.
        SCHEMA: {db_schema}
        
        OUTPUT ONLY THE SQL IN A CODE BLOCK.
        """
    else:
        follow_up = ""
        if last_query_context:
            ckey, cval = last_query_context['key'], last_query_context['value']
            follow_up = f"CONTEXT: User previously found {ckey}='{cval}'. Answer the follow-up using UPPER({ckey})=UPPER('{cval}')."
        
        prompt = f"""
        You are an expert SQL assistant for {db.dialect}.
        SCHEMA: {db_schema}
        HISTORY: {chat_history}
        QUESTION: {user_question}
        {follow_up}
        RULES: Use SELECT *, use LIMIT if requested, use GROUP BY for counts.
        OUTPUT ONLY THE SQL IN A CODE BLOCK: ```sql ... ```
        """

    return get_llm_response(prompt)

@server_app.route('/')
def index():
    session.clear()
    return render_template('index.html')

@server_app.route('/connect_db', methods=['POST'])
def connect_db():
    data = request.json
    db_type = data.get('db_type')
    username = data.get('username')
    password = quote_plus(data.get('password', ''))
    host, port, db_name = data.get('host'), data.get('port'), data.get('db_name')

    uri_map = {
        "postgresql": f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{db_name}",
        "mysql": f"mysql+mysqlconnector://{username}:{password}@{host}:{port}/{db_name}",
        "sqlite": f"sqlite:///{db_name}",
    }
    db_uri = uri_map.get(db_type)

    try:
        engine = create_engine(db_uri)
        with engine.connect() as conn: pass
        session['db_uri'] = db_uri
        session_memory[session.sid] = ConversationBufferWindowMemory(k=4, return_messages=True)
        return jsonify({"success": f"Connected to {db_name}."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@server_app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get("message")
    db_uri = session.get('db_uri')
    memory = session_memory.get(session.sid)
    
    if not db_uri or memory is None:
        return jsonify({"error": "Session or Database not found."}), 400

    engine = create_engine(db_uri)
    db = SQLDatabase(engine=engine)
    
    last_query = session.get('last_query')
    last_context = session.get('last_query_context')
    formatted_history = str(memory.chat_memory.messages[-2:]) if len(memory.chat_memory.messages) > 1 else ""

    max_attempts = 2
    attempt = 0
    error_msg = None
    sql_query = None
    structured_results = []

    while attempt < max_attempts:
        llm_raw = get_sql_query_from_llm(user_message, db, formatted_history, last_query, last_context, error_msg, sql_query)
        sql_query = extract_sql(llm_raw)
        
        print(f"[LOG] Attempt {attempt+1} SQL: {sql_query}")

        try:
            with engine.connect() as connection:
                result = connection.execute(text(sql_query))
                keys = list(result.keys())
                fetched = result.fetchall()
                structured_results = [dict(zip(keys, row)) for row in fetched]
            
            break 
        except Exception as e:
            print(f"[RETRY] SQL Failed: {e}")
            error_msg = str(e)
            attempt += 1

    if attempt == max_attempts and not structured_results:
        return jsonify({"error": "The AI tried to fix the query but failed. Try rephrasing."}), 500

    if len(structured_results) == 1 and len(structured_results[0]) == 2:
        keys, values = list(structured_results[0].keys()), list(structured_results[0].values())
        if isinstance(values[0], str) and isinstance(values[1], (int, float, Decimal)):
            session['last_query_context'] = {'key': keys[0], 'value': values[0]}

    if not structured_results:
        final_answer = "<p>No results found.</p>"
    else:
        comp = generate_comparative_answer(structured_results)
        if comp:
            final_answer = comp
        elif len(structured_results) == 1 and len(structured_results[0]) == 1:
            k = list(structured_results[0].keys())[0].replace("_", " ").title()
            v = list(structured_results[0].values())[0]
            final_answer = f"<p><strong>{k}:</strong> {v}</p>"
        else:
            final_answer = f"<p>Found {len(structured_results)} records.</p>" + generate_html_output(structured_results)

    memory.chat_memory.add_user_message(user_message)
    memory.chat_memory.add_ai_message(f"SQL: `{sql_query}`")
    session['last_query'] = sql_query
    session.modified = True
    
    return jsonify({'response': final_answer})
