# TalentScout – AI Hiring Assistant

An AI-powered hiring assistant chatbot built with **Streamlit** to assist in the **initial screening of candidates** for technology roles. The chatbot conducts a structured conversation, collects essential candidate information, and generates **experience-aware technical interview questions** based on the candidate’s declared tech stack using a Large Language Model (LLM).

---

## Key Features

- Guided, conversational hiring assistant
- Collects candidate details:
  - Full Name  
  - Email Address  
  - Phone Number  
  - Current Location  
  - Years of Experience  
  - Desired Position(s)  
  - Tech Stack
- Input validation for name, email, phone number, and experience
- Tech stack confirmation with ability to add missing technologies
- Generates **3–5 technical questions per technology**
- Question difficulty adapts based on candidate experience
- Live candidate summary sidebar for recruiter context
- Graceful exit handling and conversation completion

---

## Architecture Overview
```
├── app.py                 # Streamlit UI + conversation flow
├── llm/
│   ├── base.py            # LLM interface
│   └── ollama_llm.py      # Ollama + LLaMA implementation
├── prompts/
│   ├── system_prompt.txt
│   └── tech_questions_prompt.txt
├── utils/
│   ├── constants.py
│   └── validators.py
├── requirements.txt
└── README.md
```

**Design Highlights**
- Deterministic, state-machine-driven conversation flow  
- LLM used only for technical question generation  
- Modular and LLM-agnostic architecture  

---

## Prompt Engineering

- A **system prompt** defines role, tone, and scope boundaries.
- A **technical question prompt** dynamically injects:
  - Candidate role
  - Years of experience
  - Declared tech stack
- Question difficulty adapts automatically:
  - `< 1 year`: fundamentals  
  - `1–3 years`: applied usage and debugging  
  - `> 3 years`: design trade-offs and real-world constraints  

---

## Data Privacy

- All candidate data is stored **in-memory only**
- No database or persistent storage
- No logging of personal information
- Uses simulated data and follows GDPR-friendly practices

---

## Tech Stack

- **Python**
- **Streamlit**
- **Ollama**
- **LLaMA (local, open-source LLM)**

---

## Setup & Run

```bash
git clone https://github.com/<your-username>/TalentScout.git
cd TalentScout

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

ollama pull llama3
streamlit run app.py
```
## Demo
[A short demo video demonstrating the chatbot flow and features is provided.](https://www.loom.com/share/40afa6c92d384de790611ec494e7f769)

## Summary

This project demonstrates:  
  - Controlled LLM usage via prompt engineering  
  - Clean conversational state management
  - UX-aware validation and fallback handling
  - Modular, production-minded system design
Built as part of an AI/ML Intern assignment.
