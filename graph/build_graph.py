from langgraph.graph import END, START, StateGraph

from graph.nodes import (
    editor_node,
    formatter_node,
    researcher_node,
    writer_node,
)
from graph.router import route_after_editor
from graph.state import NewsletterState


def build_newsletter_graph():
    """
    Build and compile the Nawader newsletter workflow.

    Flow:
        START
          ↓
        Researcher
          ↓
        Writer
          ↓
        Editor
          ↓
        Conditional Router
          ├── Writer
          └── Formatter
                  ↓
                 END
    """

    # Create a graph that uses NewsletterState.
    graph_builder = StateGraph(NewsletterState)

    # Register the workflow nodes.
    graph_builder.add_node("researcher",researcher_node,)
    graph_builder.add_node("writer",writer_node,)
    graph_builder.add_node("editor",editor_node,)
    graph_builder.add_node("formatter",formatter_node,)

    # Define the linear beginning of the workflow.
    graph_builder.add_edge(START,"researcher",)
    graph_builder.add_edge("researcher","writer",)
    graph_builder.add_edge("writer","editor",)

    # After the Editor, use the Python Router function.
    graph_builder.add_conditional_edges(
        "editor",
        route_after_editor,
        {
            "writer": "writer",
            "formatter": "formatter",
        },
    )

    # Formatter is always the final node.
    graph_builder.add_edge("formatter",END,)

    # Compile the graph once.
    return graph_builder.compile()


# Pre-compiled graph shared by tests and FastAPI.
newsletter_graph = build_newsletter_graph()