from app import create_app

app = create_app()

if __name__ == "__main__":
    # use_reloader=False é importante: o scheduler de snapshots (histórico)
    # arranca em segundo plano dentro do processo, e o reloader do Flask
    # duplicaria esse processo (e os snapshots viriam a dobrar).
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)
