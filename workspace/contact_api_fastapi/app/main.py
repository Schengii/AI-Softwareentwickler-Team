from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from typing import List, Optional

app = FastAPI(title="Kontaktliste API")

class Contact(BaseModel):
    id: int
    name: str
    email: EmailStr
    phone: Optional[str] = None

class ContactCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None

contacts: List[Contact] = []
id_counter = 1

@app.get("/contacts", response_model=List[Contact])
def get_contacts():
    return contacts

@app.get("/contacts/{contact_id}", response_model=Contact)
def get_contact(contact_id: int):
    for contact in contacts:
        if contact.id == contact_id:
            return contact
    raise HTTPException(status_code=404, detail="Kontakt nicht gefunden")

@app.post("/contacts", response_model=Contact, status_code=201)
def create_contact(contact: ContactCreate):
    global id_counter
    new_contact = Contact(id=id_counter, **contact.model_dump())
    contacts.append(new_contact)
    id_counter += 1
    return new_contact

@app.put("/contacts/{contact_id}", response_model=Contact)
def update_contact(contact_id: int, contact_update: ContactCreate):
    for i, contact in enumerate(contacts):
        if contact.id == contact_id:
            updated_contact = Contact(id=contact_id, **contact_update.model_dump())
            contacts[i] = updated_contact
            return updated_contact
    raise HTTPException(status_code=404, detail="Kontakt nicht gefunden")

@app.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: int):
    for i, contact in enumerate(contacts):
        if contact.id == contact_id:
            del contacts[i]
            return None
    raise HTTPException(status_code=404, detail="Kontakt nicht gefunden")
