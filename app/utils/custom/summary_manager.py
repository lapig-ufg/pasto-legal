from typing import Optional

from agno.session import SessionSummaryManager, TeamSession
from agno.session.summary import SessionSummary


class MySessionSummaryManager(SessionSummaryManager):

    # Number of runs betwen summareis.
    runs_interval: int

    def __init__(self, runs_interval: int=5, **kwargs):
        self.runs_interval = runs_interval
        
        super().__init__(kwargs)


    def create_session_summary(
        self,
        session: TeamSession,
    ) -> Optional[SessionSummary]:
        """Creates a summary of the session"""
        session_state = session.session_data.get("session_state", None)

        if session_state:
            runs_to_next_summary = session_state.get("runs_to_next_summary", 0)

            if not runs_to_next_summary:
                session_state['runs_to_next_summary'] = self.runs_interval
                return super().create_session_summary(session)

            if not session.summary:
                return None

            return session.summary