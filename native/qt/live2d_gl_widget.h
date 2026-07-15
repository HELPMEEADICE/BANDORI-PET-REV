#pragma once

#include "bandori_live2d_ffi.h"

#include <QElapsedTimer>
#include <QOpenGLWidget>
#include <QPoint>
#include <QSize>
#include <QString>
#include <QTimer>

#include <memory>
#include <optional>

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
    void setRenderQuality(const QString& quality);
    void setDragLocked(bool locked);
    bool dragLocked() const;
    void setHeadTrackingEnabled(bool enabled);
    void setGazeTargetGlobal(const QPoint& globalPosition);
    void clearGazeTarget();
    void setHitAlphaThreshold(int threshold);
    void setLipSyncMaxOpen(double value);
    void setLipSyncPose(double level, double form = 0.0);
    bool triggerAction(const QString& action, const QString& character);
    bool applyDefaultState(
        const QString& configuredMotion,
        const QString& configuredExpression,
        const QString& character);
    bool triggerInteraction(
        const QString& region,
        const QString& configuredMotion,
        const QString& configuredExpression,
        const QString& character);

signals:
    void runtimeReady();
    void clicked(double x, double y);
    void doubleClicked(double x, double y);
    void rightClicked(int globalX, int globalY);
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
    void mouseDoubleClickEvent(QMouseEvent* event) override;

private:
    static std::uintptr_t resolveGlProcedure(const char* name, void* userData);
    bool ensureSsaaFramebuffer(const QSize& size);
    bool syncRendererTarget(const QSize& size);
    bool blitSsaaToDefault(const QSize& targetSize);
    void clearTarget(const QSize& size);
    void applyGazeTracking();
    void requestAlphaSample();
    void readPendingAlphaSample(const QSize& targetSize);
    bool isOpaqueAtGlobal(const QPoint& globalPosition);
    void applyInputPassthroughFromSample();
    void setInputPassthrough(bool enabled);
    void finishWindowDrag();
    void resetInteractionExpression(std::uint64_t token);
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
    std::uint32_t textureQuality_ = 1;
    int ssaaScale_ = 2;
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
    bool headTrackingEnabled_ = true;
    std::optional<QPoint> gazeTargetGlobal_;
    QPoint lastAppliedGazeGlobal_;
    QPoint lastAppliedGazeWindowOrigin_;
    bool gazeWasApplied_ = false;
    bool dragMoved_ = false;
    bool pressedOnModel_ = false;
    bool rightPressHandled_ = false;
    std::uint64_t interactionExpressionToken_ = 0;
    QPoint dragPressGlobal_;
    QPoint dragWindowOrigin_;
    std::unique_ptr<QOpenGLFramebufferObject> ssaaFramebuffer_;
    QSize ssaaFramebufferSize_;
    QSize rendererTargetSize_;
};

} // namespace bandori
