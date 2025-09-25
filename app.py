import streamlit as st
import uuid
from datetime import datetime, timedelta
import json
import os
import random
from datetime import datetime, timedelta
import uuid
import random
import streamlit as st
from supabase import create_client, Client
from collections import defaultdict

#from general_functions import show_and_save_questio
# Obtener datos del archivo .streamlit/secrets.toml
url: str = os.getenv("SUPABASE_URL") or st.secrets["SUPABASE_URL"]
key: str = os.getenv("SUPABASE_KEY") or st.secrets["SUPABASE_KEY"]

supabase: Client = create_client(url, key)
# -----------------------------------
# LOAD AND SAVE TEST INSTANCE DATA
# -----------------------------------

def load_test_data_from_supabase_by_code(code_input):
    #Se ejecuto el siguiente código en supabase para poder hacer la búsqueda por prefijo:
    #```create or replace function find_test_instance_by_prefix(prefix text)
    #    returns setof test_instances as $$
    #    select *
    #    from test_instances
    #    where id::text ilike prefix || '%'
    #    limit 1;
    #    $$ language sql stable;```

    response = supabase.rpc(
        "find_test_instance_by_prefix",
        {"prefix": code_input}
    ).execute()

    if response.data:
        return response.data[0]
    return None

def load_answers_from_supabase_by_code(code_input):
    """
    Carga las respuestas desde Supabase para un test_instance_id
    que empieza con `code_input`. Devuelve un dict anidado:
    {
        question_id: {
            input_id: respuesta_completa
        }
    }
    """
    response = supabase.rpc(
        "find_answers_by_test_instance_id_prefix",
        {"prefix": code_input}
    ).execute()
    if not response.data:
        return {}
    return _normalize_answers(response.data)

def build_structured_test_data_from_session():
    """
    Transforma `st.session_state.test_info` al formato estructurado que se guardará en Supabaseen la tabla tests
    """
    return { 
        "id": st.session_state.get("test_id"),
        "user_id": str(uuid.uuid4()),#st.session_state.get("user_id"),
        "seed": st.session_state.test_info.get("seed"),
        "start_timestamp": st.session_state.test_info.get("start_timestamp"),
        "name": st.session_state.test_info.get("name"),
        "email": st.session_state.test_info.get("email"),
        "birthdate": st.session_state.test_info.get("birthdate"),
        "sex": st.session_state.test_info.get("sex"),
        "gender_identity": st.session_state.test_info.get("gender_identity"),
        "education_level": st.session_state.test_info.get("education_level"),
        "occupation": st.session_state.test_info.get("occupation"),
        "country": st.session_state.test_info.get("country"),
        "zipcode": st.session_state.test_info.get("zipcode"),
        "referral_code": st.session_state.test_info.get("referral_source"),
        "paid_package": st.session_state.test_info.get("paid_package")
    }

def save_test_data_to_supabase(structured_test_data):
    response = supabase.table("test_instances").insert([structured_test_data]).execute()
    #despues agregar mesnaje de error si no se guarda

# -----------------------------------
# LOAD QUESTIONS AND INPUT STRUCTURES FROM SUPABASE
# -----------------------------------

def load_section_questions_ids_from_db(section):
    """ 
    Carga los ids que corresponden a las preguntas de una seccion desde supabase section == subtest
    Esto esta aparte para tener mas control de qué ´reguntas se ponen en cada subtest
    """
    response = supabase.table("questions").select("id").eq("subtest", section).execute()
    if not response.data:
        return {}
    return [d["id"] for d in response.data]

def load_input_structures_from_db(ids_list): 
    #ya se creo en supabase una vista que junta las preguntas y las estructuras de las preguntas
    #hacer este join de la vista es un poco redundante pero es para que sea mas facil de entender que estructuras ya respondidas se guardaran con que preguntas
    response = supabase.table("questions_with_inputs").select("*").in_("question_id", ids_list).execute()
    if not response.data:
        return {}
    return _normalize_input_structures(response.data)

def _normalize_input_structures(input_structures_list):
    """
    Convierte la lista de estructuras de preguntas en un dict indexado por question_id.
    """
    input_structures_dict = defaultdict(dict)
    for qs in input_structures_list:
        qid = qs["question_id"]
        iid = qs["input_id"]

        # options siempre viene como string -> lo cargamos a lista
        qs["options"] = json.loads(qs["options"])

        # text_json puede venir como str (JSON) o dict (Postgres JSONB)
        if qs["text_json"] is not None:
            if isinstance(qs["text_json"], str):
                text_json_value = json.loads(qs["text_json"])
            else:
                text_json_value = qs["text_json"]
        else:
            text_json_value = None
        
        #agregare esto a ver si no rompo todo 🎃
        qs["question_text"] = qs["text"]
        qs["question_structure_text"] = text_json_value.get(iid, None)

        input_structures_dict[qid][iid] = qs
        #y si no se rompe todo, los isguientes se pueden quitar 🎃
        input_structures_dict[qid]["text"] = qs["text"]
        input_structures_dict[qid]["text_json"] = text_json_value

    return dict(input_structures_dict)


def initialize_questions_order():        
    """
    Esta función maneja qué preguntas se muestran en cada sección
    y en qué orden, aquí vive la lógica de qué preguntas van en que seccion.
    st.session_state[section]["questions_ids"] 
    """
    seed = st.session_state.test_info["seed"]
    for section in sections: 
        if section not in ["bienvenida", "consentimiento", "resultados"]:
            questions_ids = load_section_questions_ids_from_db(section)
            #random.Random(seed).shuffle(questions_ids)
            if section not in st.session_state:
                st.session_state[section] = {}
            if "questions_ids" not in st.session_state[section]:
                st.session_state[section]["questions_ids"] = questions_ids
            if "input_structures" not in st.session_state[section]:
                st.session_state[section]["input_structures"] = load_input_structures_from_db(questions_ids)
#safe dbstructure to streamblit translation
def _sanitize_label(raw):
    """
    Devuelve (label_str, label_visibility) siempre válidos para Streamlit.
    - Si raw es None o vacío => " " y label_visibility="collapsed"
    - Si raw no es str => lo castea a str
    """
    if raw is None:
        return " ", "collapsed"
    if not isinstance(raw, str):
        try:
            raw = str(raw)
        except Exception:
            return " ", "collapsed"
    if raw.strip() == "":
        return " ", "collapsed"
    return raw, "visible"

def _safe_index(options, value, default=0):
    try:
        return options.index(value)
    except Exception:
        return default

def _safe_select_value(options, value):
    return value if value in options else (options[0] if options else None)

def _safe_float(x, fallback=0.0):
    try:
        return float(x)
    except Exception:
        return fallback

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


#Crear inputs desde database (dumb app) 
def show_input_structure_from_db(question_id, input_id, section, is_horizontal=True):
    structure = st.session_state[section]["input_structures"][question_id][input_id]
    previous_response = st.session_state.answers.get(question_id, {}).get(input_id, {}).get("response_text", None)
    label, label_vis = _sanitize_label(structure.get("input_text"))

    response = None
    if structure["input_type"] == "radio":
        idx = _safe_index(structure["options"], previous_response, default=0)
        response = st.radio(
            label,
            structure["options"],
            horizontal=is_horizontal,
            index=idx,
            key=f"{question_id}_{input_id}",
            label_visibility=label_vis,
        )

    elif structure["input_type"] == "selectbox":
        idx = _safe_index(structure["options"], previous_response, default=0)
        response = st.selectbox(
            label,
            structure["options"],
            index=idx,
            key=f"{question_id}_{input_id}",
            label_visibility=label_vis,
        )

    elif structure["input_type"] == "checkbox":
        val = bool(previous_response) if previous_response is not None else False
        response = st.checkbox(
            label,
            value=val,
            key=f"{question_id}_{input_id}",
            label_visibility=label_vis,
        )

    elif structure["input_type"] == "text_input":
        response = st.text_input(
            label,
            value=previous_response if previous_response is not None else "",
            key=f"{question_id}_{input_id}",
            label_visibility=label_vis,
        )

    elif structure["input_type"] == "text_area":
        response = st.text_area(
            label,
            value=previous_response if previous_response is not None else "",
            key=f"{question_id}_{input_id}",
            label_visibility=label_vis,
        )

    elif structure["input_type"] == "select_slider":
        val = _safe_select_value(structure["options"], previous_response)
        response = st.select_slider(
            label,
            options=structure["options"],
            value=val,
            key=f"{question_id}_{input_id}",
            label_visibility=label_vis,
        )

    elif structure["input_type"] == "slider":
        lo = _safe_float(structure["options"][0], 0.0)
        hi = _safe_float(structure["options"][-1], 1.0)
        if lo > hi:
            lo, hi = hi, lo  # por si vienen invertidos
        prev = _safe_float(previous_response, lo) if previous_response is not None else lo
        prev = _clamp(prev, lo, hi)
        response = st.slider(
            label,
            min_value=lo,
            max_value=hi,
            value=prev,
            step=0.01,  # o None si quieres step automático
            key=f"{question_id}_{input_id}",
            label_visibility=label_vis,
        )
    elif structure["input_type"] == "no_input":
        response = None #al ser None no se guarda en la base de datos ni en session_state
    else:
        st.error(f"Tipo de input no soportado: {structure['input_type']}")
    return response

def vspace(px=12):
    st.markdown(f"<div style='height:{px}px'></div>", unsafe_allow_html=True)


def _normalize_answers(answers_list):
    """
    Convierte la lista de respuestas en un dict indexado por question_id e input_id.
    """
    answers_dict = defaultdict(dict)
    for ans in answers_list:
        qid = ans["question_id"]
        iid = ans["input_id"]
        answers_dict[qid][iid] = ans
    return dict(answers_dict)

def format_answer_structure_for_table_answers(
    question_id, 
    input_id, 
    response_text, 
    response_value_function=None
):
    """Crea la estructura limpia para la tabla answers.
    """
    data = {
        "test_instance_id": st.session_state["test_id"],
        "question_id": question_id,
        "input_id": input_id,
        "response_text": response_text or None,
        "response_value": (
            response_value_function(response_text) 
            if response_value_function and response_text is not None 
            else None
        ),
        "structure_version": 1,
        "app_input_key": f"{question_id}_{input_id}",
        "app_source": "streamlit_with_supabase"
    }

    # Solo ponemos created_at si es realmente un insert
    if "created_at" not in data:
        data["created_at"] = datetime.now().isoformat()
    return data

def save_answer_to_supabase(formatted_answer):
    response = (
        supabase.table("answers")
        .upsert(
            formatted_answer,
            #on_conflict=["test_instance_id", "question_id", "input_id"] esta da error pero parece necesario
        )
        .execute()
    )
    return response
def save_answer_in_session_state(question_id, input_id, formatted_answer):
    if question_id not in st.session_state.answers:
        st.session_state.answers[question_id] = {}
    if input_id not in st.session_state.answers[question_id]:
        st.session_state.answers[question_id][input_id] = {}
    st.session_state.answers[question_id][input_id] = formatted_answer
import copy
def save_answer(question_id, input_id, structure_response, answer_dict, response_value_function=None):
    """
    Encapsula la logica de guardado.
    - Formatea la respuesta para la tabla answers
    - actualiza el diccionario de respuestas answer_dict (el que tiene las estructuras de la pregunta)
    - guarda la respuesta en supabase y en session_state
    - devuelve el diccionario de respuestas actualizado (solo cambia la respuesta si esta es diferente a la anterior)
    """
    formatted_answer = format_answer_structure_for_table_answers(
        question_id,
        input_id,
        structure_response,
        response_value_function=response_value_function
    )
    answer_dict_copy = copy.deepcopy(answer_dict)
    if structure_response is not None:
        answer_dict_copy[input_id] = formatted_answer
        save_answer_to_supabase(formatted_answer)
        save_answer_in_session_state(question_id, input_id, formatted_answer)
    return answer_dict_copy



#---------------------------------------------------- App  ----------------------------------------------------

# Títulos de secciones
sections = [
    "bienvenida",
    #"consentimiento",
    #"criterios_diagnosticos",
    #"factores_agudizantes_y_atenuantes",
    #"funciones_ejecutivas",
    "diagnostico_diferencial",
    #"comorbilidad_tp",
    #"otras_comorbilidades",
    "resultados",
    #"acciones_sugeridas"
]

#conforme vayamos evolucionando los tests necesitaran trazabilidad, saber qué preguntas tienen, estadísticos, etc.
subtests_ids = {
    "criterios_diagnosticos": "cd_v1",
    "factores_agudizantes_y_atenuantes": "fa_agud_aten_v1",
    "funciones_ejecutivas": "fe_v1",
    "diagnostico_diferencial": "dd_v1",
    "comorbilidad_tp": "tp_v1",
}
sections_seo =  {
    "bienvenida": "",
    "consentimiento": "Consentimiento",
    "criterios_diagnosticos": "",
    "factores_agudizantes_y_atenuantes": "",
    "funciones_ejecutivas": "",
    "diagnostico_diferencial": "Diagnóstico diferencial",
    "comorbilidad_tp": "Personalidad",
    "resultados": "Resultados",
    "acciones_sugeridas": "Acciones sugeridas"
}
spanish_to_boolean = {
    "Sí": True,
    "No": False
}

if "section_index" not in st.session_state:
    st.session_state.section_index = 0

def next_section():
    if st.session_state.section_index < len(sections) - 1:
        st.session_state.section_index += 1

def previous_section():
    if st.session_state.section_index > 0:
        st.session_state.section_index -= 1

# Renderizado dinámico por sección
section = sections[st.session_state.section_index]
titulo_centrado ="""
<style>
#mi-titulo {
  text-align: center;
}
</style>
< id="mi-titulo">
"""
titulo_centrado += f"## {sections_seo[section]}" + "</h1>"
st.markdown(titulo_centrado, unsafe_allow_html=True)
#st.markdown(f"## {sections_seo[section]}")

# Asegurar que test_id esté inicializado aunque se regrese manualmente
if "test_id" not in st.session_state:
    st.session_state["test_id"] = "anonimo"
if "test_info" not in st.session_state:
    st.session_state["test_info"] = {}
#if "seed" not in st.session_state.test_info:
#    st.session_state.test_info["seed"] = random.randint(0, 1000000)
if "answers" not in st.session_state:
    st.session_state["answers"] = {}

st.sidebar.header("Código de recuperación")
if "test_id" in st.session_state and st.session_state.test_id != "anonimo":
    st.sidebar.write(f"Tu código de recuperación es: `{st.session_state['test_id'][:6]}`")
else:
    st.sidebar.write("")

# -----------------------------------------------------------SECCIÓN BIENVENIDA ------------------------------------------------------------
# -----------------------------------
# INICIO DE SECCIÓN
# -----------------------------------
#TODO: aquí ya no guardamos en answers sino que hagamso un nuevo campo test para ser congruentes con la base de datos

if section == "bienvenida":
    st.markdown("""
    ## ¡Nos encanta que estés aquí!
    Este test está diseñado para ayudarte a explorar si los síntomas que presentas pueden estar relacionados con el TDAH u otras condiciones relacionadas.
    """)

    # Inicializar modo de bienvenida
    if "welcome_mode" not in st.session_state:
        st.session_state["welcome_mode"] = None

    if "questions" not in st.session_state:
        st.session_state["questions"] = {}

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Empezar nuevo test"):
            st.session_state["welcome_mode"] = "new"
            st.rerun()
    with col2:
        if st.button("Reanudar test con código"):
            st.session_state["welcome_mode"] = "resume"
            st.rerun()

    # NUEVO TEST
    if st.session_state["welcome_mode"] == "new":
        st.markdown("### Nuevo test")
        name = st.text_input("Nombre")
        email = st.text_input("Correo electrónico")
        birthdate = st.date_input(
            "Fecha de nacimiento",
            min_value=datetime.now() - timedelta(days=365 * 120),
            max_value=datetime.now() - timedelta(days=365 * 18),
            format="DD/MM/YYYY"
        )
        sex = st.selectbox("Sexo", [ "Femenino", "Masculino", "Prefiero no decir"])     
        gender_identity = st.selectbox("Género", ["Femenino", "Masculino", "No binario", "Otro", "Prefiero no decir"])
        if gender_identity == "Otro":
            gender_identity = st.text_input("Género (opcional)")
        education_level = st.selectbox(
                "Nivel educativo",
                ["Sin estudios formales", "Primaria", "Secundaria", "Preparatoria o equivalente",
                "Licenciatura", "Posgrado", "Otro"]
            )
        occupation = st.text_input("Ocupación")  #este que puedan añadirse varios y que sea de selección pero q puedan agregar opciones
        country = st.selectbox("País de residencia", [
                "México", "Argentina", "Colombia", "Chile", "Perú", "España", "Estados Unidos", "Otro"
            ])
        city = st.text_input("Ciudad de residencia")
        zipcode = st.text_input("Código postal")
        neurodivergence = st.selectbox("¿Tienes alguna condición neurodivergente?", ["Sí", "No"])
        diagnostic_history = "sin información"
        if neurodivergence == "Sí":
            diagnostic_history = False             #TODO: revisar si si funciona:, lo que que si neurodivergence es sí, diagnostic_history sea contestado antes de pasar a la siguiente sección
            diagnostic_history = st.text_input("¿Cuál? (si son varias, puedes ponerlas separadas por comas)")
        referral_source = st.text_input("Código de descuento (opcional)")
        paid_package = "Premium" #eventualmente dependerá de la información que jalemos de stripe

        if st.button("Comenzar"):
            if not name or not email or not birthdate or not sex or not gender_identity or not education_level or not occupation or not country or not city or not zipcode or not neurodivergence or not paid_package or not diagnostic_history:
                st.warning("Por favor, completa todos los campos antes de continuar.")
            else:
                test_id = str(uuid.uuid4())
                seed = random.randint(0, 10000)

                st.session_state["test_id"] = test_id
                if neurodivergence == "No":
                    diagnostic_history = None
                neurodivergence = spanish_to_boolean[neurodivergence]
                st.session_state["test_info"] = {
                    "id": test_id,
                    "user_id": test_id,  #PARCHE: este user_id debe tomarse de el usuario de therapia pero se pone así para que no chille supabase
                    "seed": seed,
                    "start_timestamp": str(datetime.now()),
                    "name": name,
                    "email": email,
                    "birthdate": str(birthdate),
                    "sex": sex,
                    "gender_identity": gender_identity,
                    "education_level": education_level,
                    "occupation": occupation,
                    "country": country,
                    "city": city,
                    "zipcode": zipcode,
                    "neurodivergent_label": neurodivergence,
                    "diagnostic_history": diagnostic_history,
                    "referral_code": referral_source,
                    "paid_package": paid_package
                }
                initialize_questions_order() #TODO:hay que cambiar de donde saca la info
                structured_test_data = st.session_state["test_info"]
                save_test_data_to_supabase(structured_test_data)
                st.success(f"Tu código es: `{test_id[:6]}`. Guárdalo para continuar después.")
                next_section()
                st.rerun()

    # REANUDAR SESIÓN
    elif st.session_state["welcome_mode"] == "resume":
        st.markdown("### Reanudar test")
        code_input = st.text_input("Ingresa tu código de sesión (los primeros caracteres del ID):")

        if st.button("Cargar sesión previa"):
            record = load_test_data_from_supabase_by_code(code_input)
            if record:
                st.session_state["test_id"] = record["id"]
                st.session_state["test_info"] = record 
                st.session_state["answers"] = load_answers_from_supabase_by_code(code_input) 
                initialize_questions_order()
                st.success("Sesión cargada correctamente.")
                next_section()
                st.rerun()
            else:
                st.warning("No se encontró ninguna sesión con ese código.")


# -----------------------------------------------------------SECCIÓN CONSENTIMIENTO ------------------------------------------------------------
elif section == "consentimiento":
    st.markdown("### Consentimiento informado")
    st.write("Al continuar aceptas que esta es una herramienta orientativa y no sustituye a un diagnóstico médico.")
    if st.button("Acepto y continúo"):
        st.session_state["consent_given"] = True
        next_section()
        st.rerun()

# -----------------------------------------------------------SONDEO DE HÁBITOS ------------------------------------------------------------

# -----------------------------------------------------------SECCIÓN CRITERIOS DIAGNÓSTICOS ------------------------------------------------------------
elif section == "criterios_diagnosticos":
    if "question_index_cd" not in st.session_state:
        st.session_state.question_index_cd = 0  #es un contador que no tiene nada q ver con los ids en la BD
    
    #el set de preguntas ahorita se esta cargando desde session_state.questions
    questions_set = st.session_state[section]["questions_ids"]
    question_id = questions_set[st.session_state.question_index_cd] 
    
    #TODO:barra de progreso con las preguntas ya contestadas


    #posteriormente las preguntas van a estar guardadas junto con su estructura
    st.markdown(f"### ⭐️ **{st.session_state[section]['input_structures'][question_id]['text']}**")

    
    # 1. Recuperar respuesta previa si existe
    # diccionario que con las respuestas anteriores si existen, si no existen, se pone None
    answer_dict = {f"cd_{i}_v1": st.session_state.answers.get(question_id, {}).get(f"cd_{i}_v1", {}).get("response_text", None) for i in range(1, 5)}

    # 2. Mostrar preguntas y opciones     
    #lista de booleanos que indica si se debe guardar la respuesta inmediatamente
    save_immediately = [True, True, True, False]
    for i, input_id in enumerate(answer_dict.keys()):
        structure = st.session_state[section]["input_structures"][question_id][input_id]
        if structure["upper_markdown"] is not None:
            st.markdown(structure["upper_markdown"])
        if structure["lower_markdown"] is not None:
            st.markdown(structure["lower_markdown"])
        structure_response = show_input_structure_from_db(question_id, input_id, section, is_horizontal=True)
        if save_immediately[i]:
            answer_dict = save_answer(question_id, input_id, structure_response, answer_dict, response_value_function=None)

    col11, _, col12 = st.columns(3)
    with col12:
        if st.button(" Mandar comentario"):
            # Actualizamos solo el campo de comentarios sin tocar los demás
            if answer_dict["cd_4_v1"] is not None:
                answer_dict = save_answer(question_id, "cd_4_v1", answer_dict["cd_4_v1"], answer_dict, response_value_function=None)

    # Botones de navegación
    col21, col22 = st.columns(2)
    with col21:
        if st.session_state.question_index_cd > 0:
            if st.button("Atrás"):
                st.session_state.question_index_cd -= 1
                st.rerun()

    with col22:
        # Si es la última pregunta de la sección
        if st.session_state.question_index_cd == len(questions_set) - 1:
            if answer_dict.get("cd_1_v1") is not None and answer_dict.get("cd_2_v1") is not None:
                if st.button("Finalizar sección"):
                    next_section()
            else:
                st.button("Finalizar sección", disabled=True)
        else:
            if answer_dict.get("cd_1_v1") is not None and answer_dict.get("cd_2_v1") is not None:
                if st.button("Siguiente"):
                    st.session_state.question_index_cd += 1
                    st.rerun()
            else:
                st.button("Siguiente", disabled=True)
# -----------------------------------------------------------SECCIÓN FACTORES AGUDIZANTES Y ATENUANTES ------------------------------------------------------------
elif section == "factores_agudizantes_y_atenuantes":
    st.markdown("### Subtest 2: Factores agudizantes y atenuantes")
    questions_set = st.session_state[section]["questions_ids"]
    if "faa_batch_index" not in st.session_state:
        st.session_state.faa_batch_index = 0   
    if "question_index_faa" not in st.session_state:
        st.session_state.question_index_faa = 0
    
    # Inicializar estado si es necesario
    if "partial_result" not in st.session_state:
        st.session_state.partial_result = {}
    
    if "respuestas_faa" not in st.session_state:
        st.session_state.respuestas_faa = {}

    batch_size = 3
    total_preguntas = len(questions_set)
    start_idx = st.session_state.faa_batch_index * batch_size
    end_idx = start_idx + batch_size

    batch_actual = questions_set[start_idx:end_idx]

    batch_size = 3
    total_batches = (total_preguntas + batch_size - 1) // batch_size  # redondea hacia arriba

    current_batch = st.session_state.faa_batch_index + 1  # los humanos contamos desde 1
    progress_ratio = current_batch / total_batches

    #st.markdown(f"**Progreso:** {current_batch} de {total_batches} bloques de preguntas")
    st.progress(progress_ratio)


    # Mostrar preguntas de este batch
    for question_id in batch_actual:        
        answer_dict = {f"fassc_1_v1": st.session_state.answers.get(question_id, {}).get(f"fassc_1_v1", {}).get("response_text", None)}
        
        texto = st.session_state[section]["input_structures"][question_id]["text"]
        st.markdown(f"#### ⭐️ **{texto}**")
        structure_response = show_input_structure_from_db(
            question_id,
            "fassc_1_v1",
            section, 
            is_horizontal=True
            )

        answer_dict = save_answer(
            question_id, 
            "fassc_1_v1", 
            structure_response, 
            answer_dict, 
            response_value_function=None
            )
    
    # Navegación entre batches
    col1, col2 = st.columns([1, 1])

    with col1:
        if st.session_state.faa_batch_index > 0:
            if st.button("Anterior"):
                st.session_state.faa_batch_index -= 1
                st.rerun()

    with col2:
        if end_idx < total_preguntas:
            if st.button("Siguiente"):
                st.session_state.faa_batch_index += 1
                st.rerun()
#--------------------------------------- FUNCIONES EJECUTIVAS ---------------------------------------
#TODO: COPIAR EL CÓDIGO DE LA SECCIÓN ANTERIOR
elif section == "funciones_ejecutivas":
    st.markdown("### Subtest 3: Habilidades ejecutivas")
    preguntas = st.session_state.questions["funciones_ejecutivas"]
    opciones = [
        "Para nada",
        "Pasó alguna vez",
        "Podría ser",
        "Frecuentemente así soy",
        "Me estas describiendo"
    ]
    # Inicializar estado si es necesario
    if "partial_result" not in st.session_state:
        st.session_state.partial_result = {}
    
    if "respuestas_fe" not in st.session_state:
        st.session_state.respuestas_fe = {}

    if "fe_batch_index" not in st.session_state:
        st.session_state.fe_batch_index = 0    

    batch_size = 3
    total_preguntas = len(preguntas)
    start_idx = st.session_state.fe_batch_index * batch_size
    end_idx = start_idx + batch_size

    batch_actual = preguntas[start_idx:end_idx]

    batch_size = 3
    total_preguntas = len(preguntas)
    total_batches = (total_preguntas + batch_size - 1) // batch_size  # redondea hacia arriba

    current_batch = st.session_state.fe_batch_index + 1  # los humanos contamos desde 1
    progress_ratio = current_batch / total_batches

    #st.markdown(f"**Progreso:** {current_batch} de {total_batches} bloques de preguntas")
    st.progress(progress_ratio)


    # Mostrar preguntas de este batch
    for pregunta in batch_actual:
        pregunta_id = pregunta["id"]
        texto = pregunta["text"]
       
        respuesta_anterior = st.session_state.respuestas_fe.get(pregunta_id, None)

        respuesta_nueva = st.radio(
            label=texto,
            options=opciones,
            index=opciones.index(respuesta_anterior) if respuesta_anterior in opciones else None,
            key=pregunta_id
        )

        if respuesta_nueva != respuesta_anterior:
            st.session_state.respuestas_fe[pregunta_id] = respuesta_nueva
            save_incremental_result(pregunta_id, respuesta_nueva, st.session_state["test_id"], section)
    
    
    # Navegación entre batches
    col1, col2 = st.columns([1, 1])

    with col1:
        if st.session_state.fe_batch_index > 0:
            if st.button("Anterior"):
                st.session_state.fe_batch_index -= 1
                st.rerun()

    with col2:
        if end_idx < total_preguntas:
            if st.button("Siguiente"):
                st.session_state.fe_batch_index += 1
                st.rerun()

#--------------------------------------- DIAGNÓSTICO DIFERENCIAL ---------------------------------------
elif section == "diagnostico_diferencial":
    st.markdown(" ")

    #TODO: esta parte se puede generalizar para cualquier sección (por batch o por pregunta)
    #00. Inicializar estado de la sección si es necesario
    if "pregunta_index_dd" not in st.session_state:
        st.session_state.pregunta_index_dd = 0

    #0.  Traer la info para desplegar pregunta actual
    questions_set = st.session_state[section]["questions_ids"]
    question_id = questions_set[st.session_state.pregunta_index_dd] 
    text = st.session_state[section]["input_structures"][question_id]["text"]
    structures_in_question = {k: v for k, v in st.session_state[section]["input_structures"][question_id].items() if k not in ["text", "text_json"]}
    print("structures_in_question", structures_in_question.keys(), "question_id", question_id, "--------------------------------")
    #0.1. Desplegar el texto de la pregunta actual
    st.markdown(f"### ⭐️ **{text}**")


    #1. Recuperar respuesta previa si existe 
    # Este dic tiene formato {input_id: response_text} y su proposito es usarlo para:
    #          1. Recorrer el for de abajo
    #          2. Evaluar las dependencias lógicas
    #          3. Guardar la respuesta en un lugar rápidamente accesible 
    answer_dict = {structure: st.session_state.answers.get(question_id, {}).get(structure, {}).get("response_text", None) for structure in structures_in_question}
    answer_dict = dict(sorted(answer_dict.items()))
    #TODO: la opcion correspondiente a tdah y a dim (el trastorno a diferenciar) deben shuflearse 
    answer_dict_keys = list(answer_dict.keys())


    # 2. Mostrar preguntas y opciones     
    #lista de booleanos que indica si se debe guardar la respuesta inmediatamente  
    add_divider = [True, False, False, False]   #esto depende de la cantidad de imputs, cuidado si no va  atronar!!
    spaces_between_inputs = [25, 25, 15, 25]
    for i, input_id in enumerate(answer_dict_keys):
        print("input_id", input_id)
        #2.1. Recuperar la info para desplegar los input_structures de la pregunta
        structure = st.session_state[section]["input_structures"][question_id][input_id]
        
        #2.2. Recuperar las dependencias lógicas: son restrictivas, si no se indica, se asume que se debe mostrar
        condition = structure.get("logic_structure_dependencies", None)     
        if condition is not None:
            #concatenar las condiciones con 'and', el formato en la bd es {input_id del que depende:[relacion, valor]}
            condition = ' and '.join([f'(answer_dict["{k}"] {v[0]} "{v[1]}")' for k, v in condition.items()])
        else:
            condition = "True"
        print("--------------------------------")
        print("condition", condition)
        print("eval(condition)", eval(condition))
        print("value of answer for input_id", input_id, "is", answer_dict[input_id])
        print("answer_dict[dd_1_v1]", answer_dict["dd_1_v1"])
        print("--------------------------------")
        if eval(condition):
            #2.3. Desplegar los input_structures de la pregunta junto con sus textos
            
            if structure["upper_markdown"] is not None:
                if len(str(structure["upper_markdown"])) > 0:
                    st.markdown(structure["upper_markdown"])                

            # Este texto depende del par (question_id, input_id)
            question_structure_text = structure.get("question_structure_text", None)
            if question_structure_text is not None:
                if len(str(question_structure_text)) > 0:
                    st.markdown(question_structure_text, unsafe_allow_html=True)

            #2.4. Desplegar el input_structure y guardar la respuesta en answer_dict
            structure_response = show_input_structure_from_db(question_id, input_id, section, is_horizontal=True)
            answer_dict[input_id] = structure_response

            if structure["lower_markdown"] is not None:
                if len(str(structure["lower_markdown"])) > 0:
                    st.markdown(structure["lower_markdown"])            
            print("structure", structure)
            print("structure['save_immediately']", structure["save_immediately"])
            if structure["save_immediately"]:
                db_answer_dict = save_answer(question_id, input_id, structure_response, answer_dict, response_value_function=None)
            vspace(structure["vspace_size"])
            if structure["add_divider"]:
                st.divider()
    
    # Botones de navegación. 
    # TODO: (done pero hay q hacer general) dd1_v1 debe contestarse, si se contesta si al menos uno de los otros dos se debe mover tambien
    # TODO: meter la logica de las estructuras obligatorias en la BD y que la logica para avanzar a la siguiente pregunta sea que se cumplan todas las condiciones de las estructuras obligatorias
    col21, col22 = st.columns(2)
    with col21:
        if st.session_state.pregunta_index_dd > 0:
            if st.button("Atrás"):
                st.session_state.pregunta_index_dd -= 1
                st.rerun()

    with col22:
        # Si es la última pregunta de la sección
        if st.session_state.pregunta_index_dd == len(questions_set) - 1:
            if answer_dict.get("dd_1_v1") is not None:
                if st.button("Finalizar sección"):
                    next_section()
            else:
                st.button("Finalizar sección", disabled=True)
        else:
            if answer_dict.get("dd_1_v1") is not None:
                if st.button("Siguiente"):
                    st.session_state.pregunta_index_dd += 1
                    st.rerun()
            else:
                st.button("Siguiente", disabled=True)
#
#--------------------------------------- COMORBILIDAD TP ---------------------------------------
elif section == "comorbilidad_tp":
    st.markdown("### Subtest 5: Personalidad")
    questions_set = st.session_state[section]["questions_ids"]
    if "tp_batch_index" not in st.session_state:
        st.session_state.tp_batch_index = 0   
    if "question_index_tp" not in st.session_state:
        st.session_state.question_index_tp = 0
    
    # Inicializar estado si es necesario
    if "partial_result" not in st.session_state:
        st.session_state.partial_result = {}
    
    if "respuestas_tp" not in st.session_state:
        st.session_state.respuestas_tp = {}

    batch_size = 3
    total_preguntas = len(questions_set)
    start_idx = st.session_state.tp_batch_index * batch_size
    end_idx = start_idx + batch_size

    batch_actual = questions_set[start_idx:end_idx]

    batch_size = 3
    total_batches = (total_preguntas + batch_size - 1) // batch_size  # redondea hacia arriba

    current_batch = st.session_state.tp_batch_index + 1  # los humanos contamos desde 1
    progress_ratio = current_batch / total_batches

    #st.markdown(f"**Progreso:** {current_batch} de {total_batches} bloques de preguntas")
    st.progress(progress_ratio)


    # Mostrar preguntas de este batch
    for question_id in batch_actual:        
        answer_dict = {f"cm_tp_1_v1": st.session_state.answers.get(question_id, {}).get(f"cm_tp_1_v1", {}).get("response_text", None)}
        
        texto = st.session_state[section]["input_structures"][question_id]["text"]
        print("pregunta_id", question_id)
        st.markdown(f"#### ⭐️ **{texto}**")
        structure_response = show_input_structure_from_db(
            question_id,
            "cm_tp_1_v1",
            section, 
            is_horizontal=True
            )

        answer_dict = save_answer(
            question_id, 
            "cm_tp_1_v1", 
            structure_response, 
            answer_dict, 
            response_value_function=None
            )
    # Navegación entre batches
    col1, col2 = st.columns([1, 1])

    with col1:
        if st.session_state.tp_batch_index > 0:
            if st.button("Anterior"):
                st.session_state.tp_batch_index -= 1
                st.rerun()

    with col2:
        if end_idx < total_preguntas:
            if st.button("Siguiente"):
                st.session_state.tp_batch_index += 1
                st.rerun()

#--------------------------------------- OTRAS COMORBILIDADES ---------------------------------------
elif section == "Otras comorbilidades":
    st.markdown("### Subtest 6: Comorbilidades comunes")
    st.write("Ansiedad, depresión, disautonomía, trauma, autismo, etc.")
    st.button("Siguiente", on_click=next_section)

#--------------------------------------- RESULTADOS ---------------------------------------
elif section == "Resultados":
    st.markdown("### Muchas gracias por tu tiempo. Los resultados están en proceso de elaboración.")
    #st.write("Aquí puedes mostrar orientación general según respuestas (sin diagnosticar).")
    st.button("Siguiente", on_click=next_section)

#--------------------------------------- ACCIONES SUGERIDAS ---------------------------------------
elif section == "Acciones sugeridas":
    st.markdown("### ¿Y ahora qué?")
    st.write("Descarga tu reporte, agenda con un profesional, comparte tu experiencia.")
    st.button("Volver al inicio", on_click=lambda: st.session_state.update({"section_index": 0}))


# Separador visual
#st.markdown("### ")
st.markdown("---")

# Navegación entre secciones (más hacia los extremos)
if st.session_state.section_index > 1:
    col_a, col_spacer, col_b = st.columns([2, 6, 2])
    with col_a:
        if st.session_state.section_index > 0:
            st.button("⬅️   Sección anterior", on_click=previous_section, key="btn_atras_seccion")
            #st.rerun()
    with col_b:
        if st.session_state.section_index < len(sections) - 1:
            st.button("Siguiente sección   ➡️", on_click=next_section, key="btn_siguiente_seccion")
            #st.rerun()
            #st.button("Siguiente", on_click=next_section, key="btn_siguiente")