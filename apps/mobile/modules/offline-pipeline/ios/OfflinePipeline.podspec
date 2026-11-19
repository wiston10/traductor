require 'json'

package = JSON.parse(File.read(File.join(__dir__, '..', 'package.json')))

Pod::Spec.new do |s|
  s.name           = 'OfflinePipeline'
  s.version        = package['version']
  s.summary        = package['description']
  s.author         = 'Traductor Live'
  s.homepage       = 'https://github.com/traductor-live'
  s.platforms      = { :ios => '26.0' }
  s.source         = { git: '' }
  s.static_framework = true
  s.dependency 'ExpoModulesCore'

  s.source_files = '*.{h,m,mm,swift}'
end
