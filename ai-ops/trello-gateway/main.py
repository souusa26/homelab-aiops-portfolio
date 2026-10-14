from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="Trello API Gateway",
    description="API local para acessar boards e cards do Trello",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY   = os.getenv("TRELLO_API_KEY")
API_TOKEN = os.getenv("TRELLO_TOKEN")
BASE_URL  = "https://api.trello.com/1"

def auth_params():
    return {"key": API_KEY, "token": API_TOKEN}

@app.get("/")
async def root():
    return {"status": "ok", "message": "Trello API Gateway rodando!", "docs": "/docs"}

@app.get("/me")
async def get_me():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_URL}/members/me", params=auth_params())
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

@app.get("/boards")
async def get_boards():
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/members/me/boards",
            params={**auth_params(), "fields": "id,name,desc,url,closed,prefs"}
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

@app.get("/boards/{board_id}")
async def get_board(board_id: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_URL}/boards/{board_id}", params=auth_params())
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

@app.get("/boards/{board_id}/lists")
async def get_lists(board_id: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_URL}/boards/{board_id}/lists", params=auth_params())
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

@app.get("/boards/{board_id}/cards")
async def get_cards(board_id: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/boards/{board_id}/cards",
            params={**auth_params(), "fields": "id,name,desc,idList,labels,due,url,closed"}
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

@app.get("/cards/{card_id}")
async def get_card(card_id: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_URL}/cards/{card_id}", params=auth_params())
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

@app.post("/cards")
async def create_card(name: str, idList: str, desc: str = ""):
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE_URL}/cards",
            params={**auth_params(), "name": name, "idList": idList, "desc": desc}
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()

@app.put("/cards/{card_id}")
async def update_card(card_id: str, name: str = None, desc: str = None, idList: str = None):
    params = auth_params()
    if name:   params["name"]   = name
    if desc:   params["desc"]   = desc
    if idList: params["idList"] = idList
    async with httpx.AsyncClient() as client:
        r = await client.put(f"{BASE_URL}/cards/{card_id}", params=params)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()
