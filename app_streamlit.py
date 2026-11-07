"""
Pakistan Law Bot — Streamlit Web Interface (Phase 3 Task 3-1).

A modern, interactive legal chat application powered by Streamlit and Pakistan Law Bot RAG.
Run via:
    streamlit run app_streamlit.py
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import streamlit as st
except ModuleNotFoundError:
    print("\n[Pakistan Law Bot] Streamlit is not installed in your current environment.")
    print("To run the Streamlit UI, install it with:")
    print("    pip install streamlit")
    print("\nAlternatively, you can run the zero-dependency built-in web server:")
    print("    python -m src.server\n")
    sys.exit(1)

from src.bot import ask
import src.law_registry as registry
from src import vector_store as vs
from src.config import LLM_MODEL, EMBEDDING_MODEL, TOP_K_RESULTS


def main():
    st.set_page_config(
        page_title="Pakistan Law Bot — Statutory AI Assistant",
        page_icon="🏛️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # --- Custom CSS for Styling ---
    st.markdown(
        """
        <style>
        .stChatMessage {
            border-radius: 12px;
            margin-bottom: 0.8rem;
        }
        .law-tag {
            background-color: #1e293b;
            color: #10b981;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 600;
            display: inline-block;
            margin: 2px;
        }
        .disclaimer-box {
            background-color: rgba(30, 41, 59, 0.7);
            border-left: 4px solid #f59e0b;
            padding: 10px 14px;
            border-radius: 4px;
            font-size: 0.82rem;
            color: #94a3b8;
            margin-top: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # --- Sidebar: System Status & Statutory Coverage ---
    with st.sidebar:
        st.title("🏛️ Pakistan Law Bot")
        st.caption("Citizen Legal Information System")

        # Knowledge Base Status
        try:
            col = vs.get_or_create_collection()
            chunk_count = col.count()
            st.success(f"● **Knowledge Base Active** ({chunk_count:,} chunks)")
        except Exception:
            chunk_count = 0
            st.warning("● Knowledge Base Offline / Empty")

        st.divider()

        # Loaded Laws Section
        loaded_laws = registry.get_loaded_laws()
        st.subheader(f"Statutory Coverage ({len(loaded_laws)} Acts)")
        for law_id, meta in loaded_laws.items():
            jur = meta.get("jurisdiction", "Federal")
            st.markdown(
                f"**{meta.get('short_title', law_id)}**  \n"
                f"<span class='law-tag'>{jur}</span> "
                f"<span class='law-tag'>{meta.get('category', 'general').title()}</span>  \n"
                f"<small style='color: #64748b;'>{meta.get('expected_section_count', '?')} Sections • {meta.get('year', '')}</small>",
                unsafe_allow_html=True,
            )

        st.divider()

        # Multilingual Support Info
        st.subheader("🌐 Supported Languages")
        st.markdown(
            "- **English:** Full legal terminology  \n"
            "- **Roman Urdu:** Natural colloquial queries  \n"
            "- **اردو:** مکمل اردو رسم الخط اور حوالہ جات"
        )

        st.divider()

        # Clear Chat Button
        if st.button("🧹 Clear Conversation", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

        # Provenance & Disclaimer
        st.markdown(
            """
            <div class='disclaimer-box'>
            <strong>Mandatory Notice:</strong> Answers are derived strictly from official gazette texts of Pakistani law. 
            This is legal information, not formal legal advice. Consult an advocate for litigation.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # --- Main Chat Area ---
    st.header("Pakistan Statutory Law Assistant")
    st.caption("Strict Anti-Hallucination Guardrails • Exact Section Citations • $0 Operating Cost")

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display starter questions if history is empty
    if not st.session_state.messages:
        st.info("💡 **Welcome! Ask any question regarding Pakistani tenancy, criminal, family, consumer, or cybercrime laws.**")
        cols = st.columns(3)
        sample_questions = [
            ("🏠 Tenancy", "Can my landlord evict me without a Rent Tribunal order in Punjab?"),
            ("📱 Cybercrime", "What is the punishment for online harassment under PECA?"),
            ("⚖️ Criminal", "How is a First Information Report (FIR) registered at a police station?"),
        ]
        for idx, (label, query) in enumerate(sample_questions):
            with cols[idx]:
                if st.button(f"**{label}**\n\n{query[:45]}...", key=f"starter_{idx}"):
                    st.session_state.messages.append({"role": "user", "content": query})
                    st.rerun()

    # Render chat messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("citations") and msg["citations"].get("citations_found"):
                with st.expander("⚖️ Cited Statutory Sections"):
                    cites = msg["citations"]["citations_found"]
                    st.write(", ".join(f"`{c}`" for c in cites))

    # User Input
    if prompt := st.chat_input("Ask a legal question in English, Roman Urdu, or اردو..."):
        # Append and display user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Build conversation history for multi-turn follow-ups
        history_for_bot = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[:-1]
        ]

        # Call Pakistan Law Bot pipeline
        with st.chat_message("assistant"):
            with st.spinner("Searching statutory corpus and verifying citations..."):
                result = ask(
                    prompt,
                    conversation_history=history_for_bot,
                    top_k=TOP_K_RESULTS,
                    verbose=False,
                )
                answer_text = result.get("answer", "No response could be generated.")
                st.markdown(answer_text)

                citations = result.get("citations", {})
                if citations.get("citations_found"):
                    with st.expander("⚖️ Cited Statutory Sections"):
                        st.write(", ".join(f"`{c}`" for c in citations["citations_found"]))

        # Save assistant message to session state
        st.session_state.messages.append({
            "role": "assistant",
            "content": answer_text,
            "citations": citations,
        })


if __name__ == "__main__":
    main()

