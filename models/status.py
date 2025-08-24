from extensions import db


class Status(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    background_color = db.Column(db.String(10))
    text_color = db.Column(db.String(10))
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'background_color': self.background_color,
            'text_color': self.text_color
        }