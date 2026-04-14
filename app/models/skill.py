from app.extensions import db


UserSkill = db.Table(
    "user_skills",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("skill_id", db.Integer, db.ForeignKey("skills.id"), primary_key=True),
)


class Skill(db.Model):
    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    domain_relevance = db.Column(db.JSON, nullable=False, default=list)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    users = db.relationship("User", secondary=UserSkill, back_populates="skills")

    def __repr__(self) -> str:
        return f"<Skill {self.name}>"
