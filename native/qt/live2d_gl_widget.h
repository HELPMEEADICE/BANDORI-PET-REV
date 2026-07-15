#pragma once

#include "bandori_live2d_ffi.h"

#include <QElapsedTimer>
#include <QOpenGLWidget>
#include <QPoint>
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
    void setDragLocked(bool locked);
    void setHitAlphaThreshold(int threshold);
    void setLipSyncMaxOpen(double value);
    void setLipSyncPose(double level, double form = 0.0);
    bool triggerAction(const QString& action, const QString& character);

signals:
    void windowDragStarted();
    void windowDragMoved(int totalDx, int totalDy);
    void windowDragFinished(int totalDx, int totalDy);

protected:
    void initializeGL() override;
    void resizeGL(int width, int height) override;
    void paintGL() override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;

private:
    static std::uintptr_t resolveGlProcedure(const char* name, void* userData);
    bool ensureSsaaFramebuffer(const QSize& size);
    bool syncRendererTarget(const QSize& size);
    bool blitSsaaToDefault(const QSize& targetSize);
    void clearTarget(const QSize& size);
    void requestAlphaSample();
    void readPendingAlphaSample(const QSize& targetSize);
    bool isOpaqueAtGlobal(const QPoint& globalPosition);
    void applyInputPassthroughFromSample();
    void setInputPassthrough(bool enabled);
    void disposeRuntime();
    void reportLastError(const char* operation);

    QString projectRoot_;
    QString userModelsRoot_;
    QString modelPath_;
    ModelFormat format_;
    BandoriLive2dHost* host_ = nullptr;
    QElapsedTimer frameClock_;
    qint64 lastFrameMsec_ = 0;
    qint64 lipSyncLastMsec_ = -1'000;
    double lipSyncLevel_ = 0.0;
    double lipSyncTarget_ = 0.0;
    double lipSyncForm_ = 0.0;
    double lipSyncFormTarget_ = 0.0;
    double lipSyncMaxOpen_ = 0.55;
    QTimer renderTimer_;
    QTimer alphaHitTimer_;
    int hitAlphaThreshold_ = 8;
    bool alphaSamplePending_ = false;
    bool lastAlphaSampleValid_ = false;
    bool lastAlphaSampleOpaque_ = false;
    bool inputPassthrough_ = false;
    QPoint pendingAlphaSampleGlobal_;
    QPoint lastAlphaSampleGlobal_;
    QPoint lastOpaqueGlobal_;
    qint64 lastOpaqueMsec_ = -1'000;
    bool draggingWindow_ = false;
    bool dragLocked_ = false;
    bool dragMoved_ = false;
    QPoint dragPressGlobal_;
    QPoint dragWindowOrigin_;
    std::unique_ptr<QOpenGLFramebufferObject> ssaaFramebuffer_;
    QSize ssaaFramebufferSize_;
    QSize rendererTargetSize_;
};

} // namespace bandori
