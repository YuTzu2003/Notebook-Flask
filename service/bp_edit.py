from flask import Blueprint, render_template
from modules.auth import login_required

bp_edit = Blueprint('bp_edit', __name__)

@bp_edit.route("/edit")
@login_required
def edit_page():
    return render_template("edit.html")
