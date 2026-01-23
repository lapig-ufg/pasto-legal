import textwrap

def MessageException(Exception):
    def __init__(self, title, instructions):
        self.message = textwrap.dedent(f"""
            [ERRO] {title}

            # INSTRUÇÕES
            {instructions}
            """)
        super().__init__(self.message)   