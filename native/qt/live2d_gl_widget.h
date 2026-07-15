#pragma once

#include "bandori_live2d_ffi.h"

#include <QElapsedTimer>
#include <QOpenGLWidget>
#include <QSize>
#include <QString>
#include <QTimer>

#include <memory>

class QMouseEvent;
class QOpenGLFramebufferObject;

namespace bandori {

class Live2dGlWidget final : public QOpenGLWidget {
    Q_OBJECT

public:
    enum class ModelFormat : std::uint32_t {
        Moc = 2,
        Moc3 = 3,
    };

    static void configureDefaultSurfaceFormat(bool vsync = true);

    Live2dGlWidget(
        QString projectRoot,
        QString userModelsRoot,
        QString modelPath,
        ModelFormat format,
        QWidget* parent = nullptr);
    ~Live2dGlWidget() override;

    void setFramesPerSecond(int fps);

protected:
    void initializeGL() override;
    void resizeGL(int width, int height) override;
    void paintGL() override;
    void mouseMoveEvent(QMouseEvent* event) override;

private:
    static std::uintptr_t resolveGlProcedure(const char* name, void* userData);
    bool ensureSsaaFramebuffer(const QSize& size);
    bool syncRendererTarget(const QSize& size);
    bool blitSsaaToDefault(const QSize& targetSize);
    void clearTarget(const QSize& size);
    void disposeRuntime();
    void reportLastError(const char* operation);

    QString projectRoot_;
    QString userModelsRoot_;
    QString modelPath_;
    ModelFormat format_;
    BandoriLive2dHost* host_ = nullptr;
    QElapsedTimer frameClock_;
    qint64 lastFrameMsec_ = 0;
    QTimer renderTimer_;
    std::unique_ptr<QOpenGLFramebufferObject> ssaaFramebuffer_;
    QSize ssaaFramebufferSize_;
    QSize rendererTargetSize_;
};

} // namespace bandori
