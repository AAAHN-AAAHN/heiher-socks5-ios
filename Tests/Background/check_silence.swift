// Decode the actual WAV with Apple's audio framework without starting playback.
import AVFAudio
import Foundation

let url = URL(fileURLWithPath: CommandLine.arguments[1])
let file = try AVAudioFile(forReading: url)
let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                              frameCapacity: AVAudioFrameCount(file.length))!
try file.read(into: buffer)
precondition(buffer.frameLength == 400 && buffer.format.sampleRate == 8000)
precondition(buffer.format.channelCount == 1)
let samples = buffer.floatChannelData![0]
for index in 0..<Int(buffer.frameLength) { precondition(samples[index].bitPattern == 0) }
print("PASS: Apple AVAudioFile decoded 400 samples, all exactly +0.0; 8 kHz mono, 50 ms")
