with open('src/ui/web/src/views/SettingsPage.tsx', 'r') as f:
    content = f.read()

target = """          <div className="p-6 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Anthropic API Key
              </label>
              <input
                type="password"
                name="anthropic_api_key"
                value={formData.anthropic_api_key || ''}
                onChange={handleChange}
                placeholder="sk-ant-..."
                className="w-full border-gray-300 rounded-md shadow-sm focus:border-teter-orange focus:ring-teter-orange sm:text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Google AI API Key
              </label>
              <input
                type="password"
                name="google_ai_api_key"
                value={formData.google_ai_api_key || ''}
                onChange={handleChange}
                placeholder="AIza..."
                className="w-full border-gray-300 rounded-md shadow-sm focus:border-teter-orange focus:ring-teter-orange sm:text-sm"
              />
              <p className="mt-1 text-xs text-gray-500">
                Used for Gemini 1.5 Pro and Flash fallback models.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                xAI API Key
              </label>
              <input
                type="password"
                name="xai_api_key"
                value={formData.xai_api_key || ''}
                onChange={handleChange}
                placeholder="xai-..."
                className="w-full border-gray-300 rounded-md shadow-sm focus:border-teter-orange focus:ring-teter-orange sm:text-sm"
              />
              <p className="mt-1 text-xs text-gray-500">
                Secondary fallback provider.
              </p>
            </div>
          </div>"""

replacement = """          <div className="p-6 space-y-4">
            <div className="flex items-end gap-2">
              <div className="flex-grow">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Anthropic API Key
                </label>
                <input
                  type="password"
                  name="anthropic_api_key"
                  value={formData.anthropic_api_key || ''}
                  onChange={handleChange}
                  placeholder="sk-ant-..."
                  className="w-full border-gray-300 rounded-md shadow-sm focus:border-teter-orange focus:ring-teter-orange sm:text-sm"
                />
              </div>
              <button
                type="button"
                onClick={() => testKey('anthropic', formData.anthropic_api_key)}
                className="px-3 py-2 bg-gray-100 text-gray-700 rounded border border-gray-300 hover:bg-gray-200 text-sm font-medium"
              >
                Test
              </button>
            </div>

            <div className="flex items-end gap-2">
              <div className="flex-grow">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Google AI API Key
                </label>
                <input
                  type="password"
                  name="google_ai_api_key"
                  value={formData.google_ai_api_key || ''}
                  onChange={handleChange}
                  placeholder="AIza..."
                  className="w-full border-gray-300 rounded-md shadow-sm focus:border-teter-orange focus:ring-teter-orange sm:text-sm"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Used for Gemini 1.5 Pro and Flash fallback models.
                </p>
              </div>
              <button
                type="button"
                onClick={() => testKey('google', formData.google_ai_api_key)}
                className="px-3 py-2 bg-gray-100 text-gray-700 rounded border border-gray-300 hover:bg-gray-200 text-sm font-medium mb-6"
              >
                Test
              </button>
            </div>

            <div className="flex items-end gap-2">
              <div className="flex-grow">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  xAI API Key
                </label>
                <input
                  type="password"
                  name="xai_api_key"
                  value={formData.xai_api_key || ''}
                  onChange={handleChange}
                  placeholder="xai-..."
                  className="w-full border-gray-300 rounded-md shadow-sm focus:border-teter-orange focus:ring-teter-orange sm:text-sm"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Secondary fallback provider.
                </p>
              </div>
              <button
                type="button"
                onClick={() => testKey('xai', formData.xai_api_key)}
                className="px-3 py-2 bg-gray-100 text-gray-700 rounded border border-gray-300 hover:bg-gray-200 text-sm font-medium mb-6"
              >
                Test
              </button>
            </div>
          </div>"""

content = content.replace(target, replacement)

func_target = """  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {"""

func_replacement = """  const testKey = async (provider: string, key?: string) => {
    if (!key) {
      alert("Please enter a key before testing.");
      return;
    }
    try {
      const res = await apiClient.post('/settings/test-key', { provider, key });
      if (res.valid) {
        alert(`${provider} key is valid!`);
      } else {
        alert(`Validation failed: ${res.error || 'Unknown error'}`);
      }
    } catch (e: any) {
      alert(`Error testing key: ${e.message}`);
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {"""

content = content.replace(func_target, func_replacement)

with open('src/ui/web/src/views/SettingsPage.tsx', 'w') as f:
    f.write(content)
